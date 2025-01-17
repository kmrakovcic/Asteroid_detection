import time
start_time = time.time()
import sys
import matplotlib.pyplot as plt
import matplotlib as mpl
sys.path.append("..")
import os
import argparse
import tools
import evals
import numpy as np
from lsst.daf.butler import Butler


def get_magnitude_bin(repo, output_coll):
    butler = Butler(repo)
    injection_catalog_ids = list(
        butler.registry.queryDatasets("injected_postISRCCD_catalog", collections=output_coll, instrument='HSC'))
    min_mag = 100
    max_mag = 0
    for injection_catalog_id in injection_catalog_ids:
        injection_catalog = butler.get("injected_postISRCCD_catalog",
                                       dataId=injection_catalog_id.dataId,
                                       collections=output_coll, )
        min_mag = min(min_mag, injection_catalog["integrated_mag"].min())
        max_mag = max(max_mag, injection_catalog["integrated_mag"].max())
    return min_mag, max_mag


def plot_trail_histogram(NN_data, LSST_data, true_data=None):
    fig, ax = plt.subplots()
    bins = np.arange(6, 65, 5)
    if true_data is not None:
        ax.hist(true_data, bins=bins, histtype="step", label="True asteroids")
    ax.hist(NN_data, bins=bins, histtype="step", label="NN detected asteroids")
    ax.hist(LSST_data, bins=bins, histtype="step", label="LSST stack detected asteroids")
    ax.set_xlabel("Trail length")
    ax.set_ylabel("Count")
    ax.legend()
    return fig


def plot_magnitude_histogram(NN_data, LSST_data, true_data=None):
    fig, ax = plt.subplots()
    bins = np.arange(19, 27.0, 0.5)
    if true_data is not None:
        ax.hist(true_data, bins=bins, histtype="step", label="True asteroids")
    ax.hist(NN_data, bins=bins, histtype="step", label="NN detected asteroids")
    ax.hist(LSST_data, bins=bins, histtype="step", label="LSST stack detected asteroids")
    ax.set_xlabel("Integrated Magnitude")
    ax.set_ylabel("Count")
    ax.legend()
    return fig


def plot_mask_on_axis(mask, ax):
    cmap = mpl.colors.ListedColormap(['white', 'green', 'cyan', 'red'])
    ax.imshow(mask, cmap=cmap, interpolation='nearest')
    ax.set_xticks([])
    ax.set_yticks([])
    labels = {0: 'True Negative', 1: 'True Positive', 2: 'False Positive', 3: "False Negative"}
    patches = [mpl.patches.Patch(color=cmap.colors[i], label=labels[i]) for i in range(len(cmap.colors))]
    ax.legend(handles=patches)
    return ax


def plot_input_on_axis(img, ax):
    ax.imshow(img, cmap="grey")
    ax.set_xticks([])
    ax.set_yticks([])
    return ax


def main(args):
    if args.val_index_path == "":
        args.val_index_path = None
    collections = args.collection.split(',')
    tf_dataset_paths = args.tf_dataset_path.split(',')
    if len(collections) != len(tf_dataset_paths):
        raise ValueError("Number of collections and TFrecords files should be the same")
    model_name = args.model_path.split("_")[-1].split(".")[0]
    if args.output_path[-1] != "/":
        args.output_path += "/"
    args.output_path += model_name + "/"
    if not os.path.exists(args.output_path):
        os.makedirs(args.output_path)

    if args.verbose:
        print("Model evaluating started", flush=True)
    predictions = evals.eval_tools.create_nn_prediction(tf_dataset_paths,
                                                        args.model_path,
                                                        threshold=args.threshold,
                                                        batch_size=args.batch_size,
                                                        verbose=True)
    if args.verbose:
        print("NN predictions created", flush=True)
    for i in range(len(collections)):
        dataset_name = tf_dataset_paths[i].split("/")[-1].split(".")[0]
        output_path = args.output_path + dataset_name
        inputs, truths = tools.data.create_XY_pairs(tf_dataset_paths[i])
        tp, fp, fn, mask = evals.eval_tools.get_mask(truths, predictions[i], multiprocess_size=args.cpu_count)
        if args.verbose:
            print(i, "Scoring done", flush=True)
        NN_detected_asteroids, \
            true_asteroids = evals.eval_tools.NN_comparation_histogram_data(predictions[i],
                                                                            args.val_index_path,
                                                                            args.repo_path,
                                                                            collections[i],
                                                                            column_name=["integrated_mag", "trail_length"],
                                                                            multiprocess_size=args.cpu_count)
        NN_detected_asteroids_m = NN_detected_asteroids[:, 0]
        NN_detected_asteroids_t = NN_detected_asteroids[:, 1]
        true_asteroids_m = true_asteroids[:, 0]
        true_asteroids_t = true_asteroids[:, 1]
        if args.verbose:
            print(i, "Histogram data created", flush=True)
        LSST_stack_detected_asteroids = evals.eval_tools.LSST_stack_comparation_histogram_data(args.repo_path,
                                                                                               collections[i],
                                                                                               args.val_index_path,
                                                                                               multiprocess_size=args.cpu_count,
                                                                                               column_name=["integrated_mag",
                                                                                                            "trail_length"])
        LSST_stack_detected_asteroids_m = LSST_stack_detected_asteroids[:, 0]
        LSST_stack_detected_asteroids_t = LSST_stack_detected_asteroids[:, 1]
        if args.verbose:
            print(i, "LSST stack predictions created", flush=True)
        fig_1m = plot_magnitude_histogram(NN_detected_asteroids_m, LSST_stack_detected_asteroids_m, true_asteroids_m)
        fig_1t = plot_trail_histogram(NN_detected_asteroids_t, LSST_stack_detected_asteroids_t, true_asteroids_t)
        minmag, maxmag = get_magnitude_bin(args.repo_path, collections[i])
        _ = fig_1t.suptitle("Magnitude: " + str(round(minmag, 1)) + " - " + str(round(maxmag, 1)))
        tp = tp.sum()
        fp = fp.sum()
        fn = fn.sum()

        if args.verbose:
            print("Collection:", collections[i], flush=True)
            print("True Positives:", int(tp), "False Positives:", int(fp), "False Negatives:", int(fn), flush=True)
            print("F1 score", evals.eval_tools.f1_score(tp, fp, fn),
                  "\nPrecision", evals.eval_tools.precision(tp, fp, fn),
                  "\nRecall", evals.eval_tools.recall(tp, fp, fn), flush=True)

        fig_1m.savefig(output_path + "_magnitudes.png")
        fig_1t.savefig(output_path + "_trail_lengths.png")
        with open(output_path + "_scores.txt", "w") as f:
            f.write(
                "True Positives: " + str(int(tp)) + "\nFalse Positives: " + str(int(fp)) + "\nFalse Negatives: " + str(
                    int(fn)) + "\n")
            f.write("F1 score: " + str(evals.eval_tools.f1_score(tp, fp, fn)) + "\n")
            f.write("Precision: " + str(evals.eval_tools.precision(tp, fp, fn)) + "\n")
            f.write("Recall: " + str(evals.eval_tools.recall(tp, fp, fn)) + "\n")


def parse_arguments(args):
    parser = argparse.ArgumentParser()

    parser.add_argument('--model_path', type=str,
                        default="../DATA/Trained_model_56735424.keras",
                        help='Path to the model.')
    parser.add_argument('--batch_size', type=int,
                        default=512,
                        help='Batch size for the evaluation.')
    parser.add_argument('--tf_dataset_path', type=str,
                        default="../DATA/test_01.tfrecord,../DATA/test_02.tfrecord,../DATA/test_03.tfrecord,../DATA/test_04.tfrecord",
                        help='Comma-separated list of paths to the TFrecords files.')
    parser.add_argument('--output_path', type=str,
                        default="../RESULTS/",
                        help='Path to the output folder.')
    parser.add_argument('--repo_path', type=str,
                        default="/epyc/ssd/users/kmrakovc/DATA/rc2_subset/SMALL_HSC/",
                        help='Path to the Butler repo.')
    parser.add_argument('--collection', type=str,
                        default="u/kmrakovc/runs/single_frame_injection_01,u/kmrakovc/runs/single_frame_injection_02,u/kmrakovc/runs/single_frame_injection_03,u/kmrakovc/runs/single_frame_injection_04",
                        help='Comma-separated list of collection names in the Butler repo.')
    parser.add_argument('--val_index_path', type=str,
                        default="",
                        help='Path to the validation index file.')
    parser.add_argument('--cpu_count', type=int,
                        default=9,
                        help='Number of CPUs to use.')
    parser.add_argument('--threshold', type=float,
                        default=0.5,
                        help='Threshold for the predictions.')
    parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction,
                        default=True,
                        help='Verbose output.')

    return parser.parse_args(args)


if __name__ == '__main__':
    print("Import time: {:.2f}s".format(time.time() - start_time), flush=True)
    main(parse_arguments(sys.argv[1:]))
    print("Total execution time: {:.2f}s".format(time.time() - start_time), flush=True)
