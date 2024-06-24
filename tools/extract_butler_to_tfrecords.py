from lsst.daf.butler import Butler
import numpy as np
import argparse
import sys
sys.path.append("../")
import tools.data


def main(args):
    val_index = tools.data.convert_butler_tfrecords(args.repo, args.coll, shape=(128, 128),
                                                    filename_train=args.filename_train,
                                                    filename_test=args.filename_test,
                                                    train_split=args.split,
                                                    verbose=True,
                                                    seed=args.seed)
    val_index = np.array(val_index)
    val_index.sort()
    with open(args.filename_index, 'wb') as f:
        np.save(f, val_index)


def parse_arguments(args):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, help="Path to the repo", required=True)
    parser.add_argument("--coll", type=str, help="Name of the collection", required=True)
    parser.add_argument("--filename_train", type=str, help="Filename of the train dataset", required=True)
    parser.add_argument("--filename_test", type=str, help="Filename of the test dataset", required=True)
    parser.add_argument("--filename_index", type=str, help="Filename of the index", required=True)
    parser.add_argument("--split", type=float, help="Split ratio", default=0.25)
    parser.add_argument("--seed", type=int, help="Seed for random split", default=42)
    return parser.parse_args(args)


if __name__ == "__main__":
    main(parse_arguments(sys.argv[1:]))
