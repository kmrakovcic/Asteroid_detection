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
        min_mag = min(min_mag, injection_catalog["mag"].min())
        max_mag = max(max_mag, injection_catalog["mag"].max())
    return min_mag, max_mag


def plot_trail_histogram(NN_data, LSST_data, true_data=None):
    fig, ax = plt.subplots()
    bins = np.arange(4, 74, 5)
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
    bins = np.arange(20, 25.5, 0.5)
    if true_data is not None:
        ax.hist(true_data, bins=bins, histtype="step", label="True asteroids")
    ax.hist(NN_data, bins=bins, histtype="step", label="NN detected asteroids")
    ax.hist(LSST_data, bins=bins, histtype="step", label="LSST stack detected asteroids")
    ax.set_xlabel("Magnitude")
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
    model_name = args.model_path.split("_")[-1].split(".")[0]
    if args.output_path[-1] != "/":
        args.output_path += "/"
    if not os.path.exists(args.output_path):
        os.makedirs(args.output_path)
    args.output_path += model_name
    predictions = evals.eval_tools.create_NN_prediction(args.tf_dataset_path,
                                                        args.model_path,
                                                        threshold=args.threshold,
                                                        batch_size=128,
                                                        verbose=False)
    if args.verbose:
        print("NN predictions created")
    inputs, truths = tools.data.create_XY_pairs(args.tf_dataset_path)
    tp, fp, fn, mask = evals.eval_tools.get_mask(truths, predictions, batch_size=args.cpu_count)
    if args.verbose:
        print("Scoring done")
    NN_detected_asteroids_m, \
        true_asteroids_m = evals.eval_tools.NN_comparation_histogram_data(predictions,
                                                                          args.val_index_path,
                                                                          args.repo_path,
                                                                          args.collection,
                                                                          column_name="mag",
                                                                          batch_size=args.cpu_count)
    if args.verbose:
        print("Histogram data for magnitudes created")
    NN_detected_asteroids_t, \
        true_asteroids_t = evals.eval_tools.NN_comparation_histogram_data(predictions,
                                                                          args.val_index_path,
                                                                          args.repo_path,
                                                                          args.collection,
                                                                          column_name="trail_length",
                                                                          batch_size=args.cpu_count)
    if args.verbose:
        print("Histogram data for trail length created")
    LSST_stack_detected_asteroids_m = evals.eval_tools.LSST_stack_comparation_histogram_data(args.repo_path,
                                                                                             args.collection,
                                                                                             args.val_index_path,
                                                                                             batch_size=args.cpu_count,
                                                                                             column_name="mag")
    if args.verbose:
        print("LSST stack predictions for magnitudes created")
    LSST_stack_detected_asteroids_t = evals.eval_tools.LSST_stack_comparation_histogram_data(args.repo_path,
                                                                                             args.collection,
                                                                                             args.val_index_path,
                                                                                             batch_size=args.cpu_count)
    if args.verbose:
        print("LSST stack predictions for trail length created")

    fig_1m = plot_magnitude_histogram(NN_detected_asteroids_m, LSST_stack_detected_asteroids_m, true_asteroids_m)
    fig_1t = plot_trail_histogram(NN_detected_asteroids_t, LSST_stack_detected_asteroids_t, true_asteroids_t)
    minmag, maxmag = get_magnitude_bin(args.repo_path, args.collection)
    _ = fig_1t.suptitle("Magnitude: " + str(round(minmag, 1)) + " - " + str(round(maxmag, 1)))
    tp = tp1.sum()
    fp = fp1.sum()
    fn = fn1.sum()

    if args.verbose:
        print("True Positives:", int(tp), "False Positives:", int(fp), "False Negatives:", int(fn))
        print("F1 score", evals.eval_tools.f1_score(tp, fp, fn),
              "\nPrecision", evals.eval_tools.precision(tp, fp, fn),
              "\nRecall", evals.eval_tools.recall(tp, fp, fn))

    fig_1m.savefig(args.output_path + "_magnitudes.png")
    fig_1t.savefig(args.output_path + "_trail_lengths.png")
    with open(args.output_path + "_scores.txt", "w") as f:
        f.write("True Positives: " + str(int(tp)) + " False Positives: " + str(int(fp)) + " False Negatives: " + str(
            int(fn)) + "\n")
        f.write("F1 score: " + str(evals.eval_tools.f1_score(tp, fp, fn)) + "\n")
        f.write("Precision: " + str(evals.eval_tools.precision(tp, fp, fn)) + "\n")
        f.write("Recall: " + str(evals.eval_tools.recall(tp, fp, fn)) + "\n")

    def parse_arguments(args):
        parser = argparse.ArgumentParser()

        parser.add_argument('--model_path', type=str,
                            default="../DATA/Trained_model_18796700.keras",
                            help='Path to the model.')
        parser.add_argument('--tf_dataset_path', type=str,
                            default="../DATA/test1.tfrecord",
                            help='Path to the TFrecords file.')
        parser.add_argument('--output_path', type=str,
                            default="../RESULTS/",
                            help='Path to the output folder.')
        parser.add_argument('--repo_path', type=str,
                            default="../DATA/rc2_subset/SMALL_HSC/",
                            help='Path to the Butler repo.')
        parser.add_argument('--collection', type=str,
                            default="u/kmrakovc/single_frame_injection_01",
                            help='Collection name in the Butelr repo.')
        parser.add_argument('--val_index_path', type=str,
                            default="../DATA/val_index1.npy",
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
        main(parse_arguments(sys.argv[1:]))
