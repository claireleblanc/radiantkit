'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

import argparse
from ggc.prompt import ask
from ggc.args import check_threads, export_settings
import logging
import numpy as np
import os
from radiantkit.const import __version__
from radiantkit import particle
from radiantkit import path
from radiantkit.report import report_select_nuclei
import re
import sys
from typing import List

logging.basicConfig(level=logging.INFO, format='%(asctime)s ' +
    '[P%(process)s:%(module)s:%(funcName)s] %(levelname)s: %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S')

def init_parser(subparsers: argparse._SubParsersAction
    ) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(__name__.split(".")[-1], description = '''
Select nuclei (objects) from segmented images based on their size (volume in 3D,
area in 2D) and integral of intensity from raw image.

To achieve this, the script looks for mask/raw image pairs in the input folder.
Mask images are identified by the specified prefix/suffix. For example, a pair
with suffix "mask" would be:
    [RAW] "dapi_001.tiff" and [MASK] "dapi_001.mask.tiff".

Nuclei are extracted and size and integral of intensity are calculated. Then,
their density profile is calculated across all images. A sum of Gaussian is fit
to the profiles and a range of +-k_sigma around the peak of the first Gaussian
is selected. If the fit fails, a single Gaussian is fitted and the range is 
selected in the same manner around its peak. If this fit fails, the selected
range corresponds to the FWHM range around the first peak of the profiles. In
the last scenario, k_sigma is ignored.

A tabulation-separated table is generated with the nuclear features and whether
they pass the filter(s). Alongside it, an html report is generated with
interactive data visualization.
''', formatter_class = argparse.RawDescriptionHelpFormatter,
        help = "Select G1 nuclei.")

    parser.add_argument('input', type=str,
        help='Path to folder containing deconvolved tiff images.')

    parser.add_argument('--k-sigma', type=float, metavar="NUMBER",
        help="""Suffix for output binarized images name.
        Default: 2.5""", default=2.5)
    parser.add_argument('--mask-prefix', type=str, metavar="TEXT",
        help="""Prefix for output binarized images name.
        Default: ''.""", default='')
    parser.add_argument('--mask-suffix', type=str, metavar="TEXT",
        help="""Suffix for output binarized images name.
        Default: 'mask'.""", default='mask')

    parser.add_argument('--version', action='version',
        version='%s %s' % (sys.argv[0], __version__,))

    advanced = parser.add_argument_group("Advanced")
    advanced.add_argument('--uncompressed',
        action='store_const', dest='compressed',
        const=False, default=True,
        help='Generate uncompressed TIFF binary masks.')
    default_inreg='^.*\.tiff?$'
    advanced.add_argument('--inreg', type=str, metavar="REGEXP",
        help="""Regular expression to identify input TIFF images.
        Default: '%s'""" % (default_inreg,), default=default_inreg)
    advanced.add_argument('-t', type=int, metavar="NUMBER", dest="threads",
        help="""Number of threads for parallelization. Default: 1""",
        default=1)
    advanced.add_argument('-y', '--do-all', action='store_const',
        help="""Do not ask for settings confirmation and proceed.""",
        const=True, default=False)

    parser.set_defaults(parse=parse_arguments, run=run)

    return parser

def parse_arguments(args: argparse.Namespace) -> argparse.Namespace:
    args.version = __version__

    args.inreg = re.compile(args.inreg)
    if 0 != len(args.mask_prefix):
        if '.' != args.mask_prefix[-1]:
            args.mask_prefix = f"{args.mask_prefix}."
    if 0 != len(args.mask_suffix):
        if '.' != args.mask_suffix[0]:
            args.mask_suffix = f".{args.mask_suffix}"

    args.threads = check_threads(args.threads)

    return args

def print_settings(args: argparse.Namespace, clear: bool = True) -> str:
    s = f"""
# Nuclei selection v{args.version}

---------- SETTING :  VALUE ----------

   Input directory :  '{args.input}'

       Mask prefix :  '{args.mask_prefix}'
       Mask suffix :  '{args.mask_suffix}'
        Compressed :  {args.compressed}

           Threads :  {args.threads}
            Regexp :  {args.inreg.pattern}
    """
    if clear: print("\033[H\033[J")
    print(s)
    return(s)

def confirm_arguments(args: argparse.Namespace) -> None:
    settings_string = print_settings(args)
    if not args.do_all: ask("Confirm settings and proceed?")

    assert os.path.isdir(args.input
        ), f"image folder not found: {args.input}"

    with open(os.path.join(args.input, "select_nuclei.config.txt"), "w+") as OH:
        export_settings(OH, settings_string)

def run(args: argparse.Namespace) -> None:
    confirm_arguments(args)
    
    imglist = path.find_re(args.input, args.inreg)
    masklist = path.select_by_prefix_and_suffix(
        args.input, imglist, args.mask_prefix, args.mask_suffix)
    raw_mask_pairs = path.pair_raw_mask_images(
        args.input, masklist, args.mask_prefix, args.mask_suffix)
    logging.info(f"working on {len(raw_mask_pairs)}/{len(imglist)} images.")
    assert 0 != len(raw_mask_pairs)

    nuclei = particle.NucleiList.from_multiple_fields_of_view(
        raw_mask_pairs, args.input, args.threads)
    logging.info(f"extracted {len(nuclei)} nuclei.")

    nuclei_data, details = nuclei.select_G1(args.k_sigma)

    np.set_printoptions(formatter={'float_kind':'{:.2E}'.format})
    logging.info(f"size fit:\n{details['size']['fit']}")
    np.set_printoptions(formatter={'float_kind':'{:.2E}'.format})
    logging.info(f"size range: {details['size']['range']}")
    np.set_printoptions(formatter={'float_kind':'{:.2E}'.format})
    logging.info(f"intensity sum fit:\n{details['isum']['fit']}")
    np.set_printoptions(formatter={'float_kind':'{:.2E}'.format})
    logging.info(f"intensity sum range: {details['isum']['range']}")

    ndpath = os.path.join(args.input, "select_nuclei.data.tsv")
    logging.info(f"writing nuclear data to:\n{ndpath}")
    nuclei_data.to_csv(ndpath, sep="\t", index=False)

    report_path = os.path.join(args.input, "select_nuclei.report.html")
    logging.info(f"writing report to\n{report_path}")
    report_select_nuclei(args, report_path, data=nuclei_data,
        size_range=details['size']['range'],
        intensity_sum_range=details['isum']['range'],
        raw_mask_pairs=sorted(raw_mask_pairs))
