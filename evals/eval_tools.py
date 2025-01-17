import tools
from astroML.crossmatch import crossmatch_angular
import numpy as np
import pandas as pd
import multiprocessing
import tensorflow as tf
import os
from collections import deque
import matplotlib.pyplot as plt


def create_nn_prediction(dataset_path, model_path="../DATA/Trained_model", threshold=0.5, batch_size=1024,
                         verbose=True):
    if type(dataset_path) is str:
        dataset_path = [dataset_path]
        dataset_path_iterable = False
    else:
        dataset_path_iterable = True
    predictions_list = ()
    if len(tf.config.list_physical_devices('GPU')) == 0:
        if verbose:
            print("No GPU detected")
        mirrored_strategy = tf.distribute.get_strategy()
    else:
        mirrored_strategy = tf.distribute.MirroredStrategy()
    with mirrored_strategy.scope():
        model = tf.keras.models.load_model(model_path, compile=False, safe_mode=False)
    for i, dataset in enumerate(dataset_path):
        if not os.path.exists(dataset):
            raise FileNotFoundError(f"Dataset {dataset} not found")

        dataset_test = tf.data.TFRecordDataset([dataset])
        tfrecord_shape = tools.model.get_shape_of_quadratic_image_tfrecord(dataset_test)
        dataset_test = dataset_test.interleave(lambda x: tf.data.Dataset.from_tensors(
            tools.model.parse_function(img_shape=tfrecord_shape, test=True)(x)),
                                               num_parallel_calls=tf.data.experimental.AUTOTUNE)
        dataset_test = dataset_test.batch(batch_size).prefetch(tf.data.experimental.AUTOTUNE)
        predictions = model.predict(dataset_test, verbose=1 if verbose else 0)
        if threshold > 0:
            predictions = (predictions > threshold).astype(float)
        else:
            predictions = predictions.astype(float)
        if not tuple(model.outputs[0].shape[1:]) == tfrecord_shape:
            with tf.device("/cpu:0"):
                predictions = np.array(tf.image.resize(predictions, tfrecord_shape[:-1]))
        if threshold > 0:
            predictions = np.ceil(predictions)
        predictions = tools.data.npy_merge(predictions, (4176, 2048))
        if not dataset_path_iterable:
            return predictions
        else:
            predictions_list += (predictions,)
    return predictions_list


def get_injection_catalog(butler, collection):
    injection_catalog_ids = np.unique(np.array(list(butler.registry.queryDatasets("injection_catalog",
                                                                                  collections=collection,
                                                                                  instrument='HSC',
                                                                                  findFirst=True))))
    injection_catalog = [butler.get("injection_catalog",
                                    dataId=i.dataId,
                                    collections=collection).to_pandas() for i in injection_catalog_ids]
    return pd.concat(injection_catalog).set_index("injection_id").sort_index()


def get_one_image_mask(true_img, prediction_img, pixel_gap=15):
    p_img = prediction_img != 0
    t_img = true_img != 0
    mask = np.zeros((t_img.shape))
    tp = 0
    fp = 0
    fn = 0
    visited = None
    while p_img.sum() != 0:
        roots = np.where(p_img != 0)
        mask_p, visited = FDS(p_img, (roots[0][0], roots[1][0]), pixel_gap, visited_pixels=visited)
        if np.any(mask_p * true_img != 0):
            tp += 1
            mask[mask_p != 0] = 1
        else:
            fp += 1
            mask[mask_p != 0] = 2
    visited = None
    while t_img.sum() != 0:
        roots = np.where(t_img != 0)
        mask_t, visited = FDS(t_img, (roots[0][0], roots[1][0]), pixel_gap=1, visited_pixels=visited)
        if not np.any(mask_t * prediction_img != 0):
            fn += 1
            mask[mask_t != 0] = 3
    return tp, fp, fn, mask


def get_mask(truths, predictions, multiprocess_size=None):
    if multiprocess_size is None:
        multiprocess_size = max(1, min(os.cpu_count() - 1, truths.shape[0]))
    if multiprocess_size > 1:
        parameters = [(truths[i], predictions[i]) for i in range(truths.shape[0])]
        with multiprocessing.Pool(multiprocess_size) as pool:
            results = pool.starmap(get_one_image_mask, parameters)
    else:
        results = [None] * truths.shape[0]
        for i in range(truths.shape[0]):
            results[i] = get_one_image_mask(truths[i], predictions[i])
    masks = np.empty(truths.shape)
    true_positive = np.empty(truths.shape[0])
    false_positive = np.empty(truths.shape[0])
    false_negative = np.empty(truths.shape[0])

    for i, (tp, fp, fn, mask) in enumerate(results):
        true_positive[i] = tp
        false_positive[i] = fp
        false_negative[i] = fn
        masks[i, :, :] = mask
    return true_positive, false_positive, false_negative, masks


def FDS(img, roots, pixel_gap, visited_pixels=None):
    if visited_pixels is None:
        visited_pixels = np.zeros(img.shape, dtype=bool)
    height, width = img.shape
    todo = deque([(roots[0], roots[1])])
    mask = np.zeros((height, width), dtype=bool)

    while todo:
        j, i = todo.pop()
        if not visited_pixels[j, i] and img[j, i] != 0:
            visited_pixels[j, i] = True
            img[j, i] = False
            mask[j, i] = True
            j_min = max(j - pixel_gap, 0)
            j_max = min(j + pixel_gap + 1, height)
            i_min = max(i - pixel_gap, 0)
            i_max = min(i + pixel_gap + 1, width)
            for jj in range(j_min, j_max):
                for ii in range(i_min, i_max):
                    if not visited_pixels[jj, ii]:
                        todo.append((jj, ii))

    return mask, visited_pixels


def one_image_hits(butler, injected_calexp_ref, postisrccd_catalog_ref,
                   output_coll, calexp_dimensions, n, stack_source_catalog_id=None,
                   nn_predictions=None, cutouts_path=""):
    injected_calexp_wcs = butler.get("injected_calexp.wcs",
                                     dataId=injected_calexp_ref.dataId,
                                     collections=output_coll)
    injected_postisrccd_catalog = butler.get("injected_postISRCCD_catalog",
                                             dataId=postisrccd_catalog_ref.dataId,
                                             collections=output_coll)
    image_data = butler.get('injected_calexp', dataId=injected_calexp_ref.dataId, collections=output_coll)

    results = [None] * len(injected_postisrccd_catalog)

    # Set up stack predictions if applicable
    if stack_source_catalog_id is not None:
        src_catalog = butler.get("src",
                                 dataId=stack_source_catalog_id.dataId,
                                 collections=output_coll)
        injected_src_catalog = butler.get("injected_src",
                                          dataId=stack_source_catalog_id.dataId,
                                          collections=output_coll)
        photocalib = butler.get("injected_calexp.photoCalib",
                                dataId=injected_calexp_ref.dataId,
                                collections=output_coll)
        snr = np.array(injected_src_catalog["base_PsfFlux_instFlux"]) / np.array(
            injected_src_catalog["base_PsfFlux_instFluxErr"])
        magnitude = photocalib.instFluxToMagnitude(injected_src_catalog, 'base_PsfFlux')
        sc = src_catalog.asAstropy().to_pandas()
        isc = injected_src_catalog.asAstropy().to_pandas()
        dist, ind = crossmatch_angular(isc[['coord_ra', 'coord_dec']].values,
                                       sc[['coord_ra', 'coord_dec']].values, 0.04 / 3600)

        stack_detection_origins = injected_calexp_wcs.skyToPixelArray(
            np.array([injected_src_catalog["coord_ra"][np.isinf(dist)]]),
            np.array([injected_src_catalog["coord_dec"][np.isinf(dist)]]),
            degrees=False)
        stack_detection_index = np.array(injected_src_catalog["id"][np.isinf(dist)]).flatten()
        stack_predictions = np.zeros(calexp_dimensions)
        stack_predictions[
            stack_detection_origins[1].astype(int), stack_detection_origins[0].astype(int)] = stack_detection_index
    else:
        stack_predictions = 0

    # Process each asteroid trail
    injected_origin = injected_calexp_wcs.skyToPixelArray(np.array([injected_postisrccd_catalog["ra"]]),
                                                          np.array([injected_postisrccd_catalog["dec"]]),
                                                          degrees=True)
    injected_angle = injected_postisrccd_catalog["beta"]
    injected_length = injected_postisrccd_catalog["trail_length"]

    for i, catalog_row in enumerate(injected_postisrccd_catalog):
        injected_mask = tools.data.draw_one_line(np.zeros(calexp_dimensions),
                                                 (injected_origin[0][i], injected_origin[1][i]),
                                                 injected_angle[i], injected_length[i])
        result = {'injection_id': catalog_row['injection_id'],
                  'ra': catalog_row['ra'],
                  'dec': catalog_row['dec'],
                  'trail_length': catalog_row['trail_length'],
                  'beta': catalog_row['beta'],
                  'surface_brightness': catalog_row['mag'],
                  'detector': injected_calexp_ref.dataId["detector"],
                  'visit': injected_calexp_ref.dataId["visit"],
                  'band': injected_calexp_ref.dataId["band"],
                  'n': n,
                  'x': round(injected_origin[1][i]),
                  'y': round(injected_origin[0][i])}

        # Neural network detection flag
        if nn_predictions is not None:
            result["NN_detected"] = int(((injected_mask == 1) & (nn_predictions == 1)).sum() > 0)

        # Stack detection processing
        if stack_source_catalog_id is not None:
            if (injected_mask * stack_predictions).sum() > 0:
                intersection_injection_stack = injected_mask * stack_predictions
                stack_index = int(intersection_injection_stack[np.where(intersection_injection_stack != 0)][0])
                result["stack_detected"] = 1
                result["stack_magnitude"] = magnitude[isc["id"] == stack_index].flatten()[0]
                result["stack_snr"] = snr[isc["id"] == stack_index].flatten()[0]
            else:
                result["stack_detected"] = 0
                result["stack_magnitude"] = None
                result["stack_snr"] = None

        # Create cutout if cutouts_path is provided
        if cutouts_path != "":
            calexp_image = image_data.image.array
            calexp_mask = image_data.mask
            if nn_predictions is None:
                fig = create_cutout(calexp_image, true_image, result["x"], result["y"], result["beta"],
                                    result["trail_length"], catalog_row['integrated_mag'], result["stack_detected"],
                                    calexp_mask=calexp_mask, NN_image=None, NN_detected=None)
            else:
                fig = create_cutout(calexp_image, injected_mask, result["x"], result["y"], result["beta"],
                                    result["trail_length"], catalog_row['integrated_mag'], result["stack_detected"],
                                    calexp_mask=calexp_mask, NN_image=nn_predictions, NN_detected=result["NN_detected"])

            fig.savefig(os.path.join(cutouts_path, f"{result['injection_id']}.png"))
            plt.close(fig)
            result["image_path"] = os.path.join(cutouts_path, f"{result['injection_id']}.png")

        results[i] = result

    return results


def create_cutout(calexp_image, true_image, x, y, beta, trail_length, magnitude, stack_detected,
                  min_size=50, calexp_mask=None, NN_image=None, NN_detected=None):
    #calexp_image = np.abs(calexp_image)
    size = max([min_size,
                np.abs((trail_length * np.cos((np.pi / 180) * beta))),
                np.abs((trail_length * np.sin((np.pi / 180) * beta)))])
    calexp_std = calexp_image.std()
    x_start = x - int(np.ceil(size / 2))
    x_stop = x + int(np.ceil(size / 2))
    y_start = y - int(np.ceil(size / 2))
    y_stop = y + int(np.ceil(size / 2))

    if x_start < 0:
        x_start = 0
    if x_stop > calexp_image.shape[0]:
        x_stop = calexp_image.shape[0]
    if y_start < 0:
        y_start = 0
    if y_stop > calexp_image.shape[1]:
        y_stop = calexp_image.shape[1]

    # Determine the number of subplots (2 or 3 based on NN_image)
    if NN_image is not None:
        fig, ax = plt.subplots(1, 3, figsize=(10, 5))
    else:
        fig, ax = plt.subplots(1, 2, figsize=(7, 5))

    # Remove axis ticks
    for a in ax:
        a.set_xticks([])
        a.set_yticks([])

    # Display images in the subplots
    ax[0].imshow(calexp_image[x_start:x_stop, y_start:y_stop], vmin=-3 * calexp_std, vmax=5 * calexp_std, cmap="gray")
    if calexp_mask is not None:
        bit=calexp_mask.getPlaneBitMask('DETECTED')
        detected_mask=np.where(np.bitwise_and(calexp_mask.array, bit), 1, 0)
        ax[0].imshow(detected_mask[x_start:x_stop, y_start:y_stop], cmap="Greens", alpha=0.3)

    ax[1].imshow(true_image[x_start:x_stop, y_start:y_stop], cmap="gray")
    if NN_image is not None:
        ax[2].imshow(NN_image[x_start:x_stop, y_start:y_stop], cmap="gray")

    # Prepare the title text
    title = f"Integrated mag={round(magnitude, 2)}\nTrail length={round(trail_length, 2)}\nStack detected={stack_detected}"
    if NN_detected is not None:
        title += f"\nNN detected={NN_detected}"

    # Set figure title
    fig.suptitle(title, fontsize=12)

    # Adjust the layout for tighter fit
    fig.tight_layout(rect=[0, 0, 1, 0.94])  # Adjust rect to leave less space for the title
    fig.subplots_adjust(top=0.85)  # Bring the title closer by reducing top margin further

    return fig


def recovered_sources(repo, collection, nn_predictions=None, val_index=None, n_parallel=1, cutouts_path=""):
    from lsst.daf.butler import Butler
    butler = Butler(repo)
    postisrccd_catalog_ref = np.unique(np.array(list(butler.registry.queryDatasets("injected_postISRCCD_catalog",
                                                                                   collections=collection,
                                                                                   instrument='HSC',
                                                                                   findFirst=True))))
    injected_calexp_ref = np.unique(np.array(list(butler.registry.queryDatasets("injected_calexp",
                                                                                collections=collection,
                                                                                instrument='HSC',
                                                                                findFirst=True))))
    source_catalog_ids = np.unique(np.array(list(butler.registry.queryDatasets("injected_src",
                                                                               collections=collection,
                                                                               instrument='HSC',
                                                                               findFirst=True))))
    calexp_dimensions = butler.get("injected_calexp.dimensions",
                                   dataId=injected_calexp_ref[0].dataId,
                                   collections=collection)
    calexp_dimensions = (calexp_dimensions.y, calexp_dimensions.x)
    injection_catalog = get_injection_catalog(butler, collection)
    if val_index is None:
        val_index = list(range(len(injected_calexp_ref)))
    if nn_predictions is None:
        nn_predictions = [None] * len(injected_calexp_ref)
    parameters = [(butler, injected_calexp_ref[i], postisrccd_catalog_ref[i],
                   collection, calexp_dimensions, i, source_catalog_ids[i], nn_predictions[i], cutouts_path) for i in val_index]
    if n_parallel > 1:
        with multiprocessing.Pool(n_parallel) as pool:
            results = pool.starmap(one_image_hits, parameters)
    else:
        results = [None] * len(parameters)
        for i, p in enumerate(parameters):
            results[i] = one_image_hits(*p)
            print("\r", i + 1, "/", len(parameters), end="")
    results = pd.DataFrame(list(np.concatenate(results).flatten())).set_index("injection_id").sort_index()
    return injection_catalog.merge(results)
