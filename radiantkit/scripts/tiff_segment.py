'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

import argparse
from ggc.prompt import ask
from ggc.args import check_threads, export_settings
from joblib import delayed, Parallel
import logging
import numpy as np
import os
from radiantkit import const, segmentation
from radiantkit.image import Image, ImageBinary, ImageLabeled
import re
import sys
from tqdm import tqdm

def parse_arguments() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description='''
Perform automatic 3D segmentation of TIFF images. The default parameters are
optimized for nuclear DNA staining and voxel size of 0.13x0.13x0.3 uM.

The input images are first identified based on a regular expression matched to
the file name. Then, they are re-scaled (if deconvolved with Huygens software).
Afterwards, a global (Otsu) and local (gaussian) thresholds are applied to
binarize the image in 3D. Finally, holes are filled in 3D and a closing
operation is performed to remove small objects. Finally. objects are filtered
based on XY projected and Z size. Moreover, objects touching the XY image
borders are discarded.

If a folder path is provided with the -2 option, any binary file with name
matching the one of an input image will be combined to the binarized image.

Use the --labeled flag to label identified objects with different intensity
levels. By default, the script generates compressed binary tiff images; use the
--uncompressed flag to generate normal tiff images instead.

Input images that have the specified prefix and suffix are not segmented.
    ''', formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('input', type=str,
        help='Path to folder containing deconvolved tiff images.')

    parser.add_argument('-o', type=str, metavar="DIRPATH", dest="output",
        help='''Path to output folder where to save binarized images (created
        if missing). Defaults to the input folder.''')
    parser.add_argument('--outprefix', type=str, metavar="TEXT",
        help="""Prefix for output binarized images name.
        Default: ''.""", default='')
    parser.add_argument('--outsuffix', type=str, metavar="TEXT",
        help="""Suffix for output binarized images name.
        Default: 'mask'.""", default='mask')
    parser.add_argument('--neighbour', type=int, metavar="NUMBER",
        help="""Side of neighbourhood region for adaptig thresholding.
        Must be odd. Default: 101""", default=101)
    parser.add_argument('--radius', type=float, nargs=2,
        help="""Filter range of object radii [px]. Default: [10, Inf]""",
        default=[10., float('Inf')], metavar=("MIN_RADIUS", "MAX_RADIUS"))
    parser.add_argument('--min-Z', type=float, metavar='FRACTION',
        help="""Minimum stack fraction occupied by an object. Default: .25""",
        default=.25)
    parser.add_argument('--mask-2d', type=str, metavar="DIRPATH",
        help="""Path to folder with 2D masks with matching name,
        to combine with 3D masks.""")
    parser.add_argument('--dilate-fill-erode', type=int, metavar="NUMBER",
        help="""Number of pixels for dilation/erosion steps
        in a dilate-fill-erode operation. Default: 0. Set to 0 to skip.""",
        default=0)

    parser.add_argument('--clear-Z',
        action='store_const', dest='do_clear_Z',
        const=True, default=False,
        help="""Remove objects touching the bottom/top of the stack.""",)
    parser.add_argument('--debug',
        action='store_const', dest='debug_mode',
        const=True, default=False,
        help='Log also debugging messages.')
    parser.add_argument('--labeled',
        action='store_const', dest='labeled',
        const=True, default=False,
        help='Export masks as labeled instead of binary.')
    parser.add_argument('--uncompressed',
        action='store_const', dest='compressed',
        const=False, default=True,
        help='Generate uncompressed TIFF binary masks.')
    
    default_inreg='^.*\.tiff?$'
    parser.add_argument('--inreg', type=str, metavar="REGEXP",
        help="""Regular expression to identify input TIFF images.
        Default: '%s'""" % (default_inreg,), default=default_inreg)
    parser.add_argument('-t', type=int, metavar="NUMBER", dest="threads",
        help="""Number of threads for parallelization. Default: 1""",
        default=1)
    parser.add_argument('-y', '--do-all', action='store_const',
        help="""Do not ask for settings confirmation and proceed.""",
        const=True, default=False)

    version="3.1.1"
    parser.add_argument('--version', action='version',
        version='%s %s' % (sys.argv[0], version,))

    args = parser.parse_args()
    args.version = version

    if args.output is None: args.output = args.input

    args.inreg = re.compile(args.inreg)
    if 0 != len(args.outprefix):
        if '.' != args.outprefix[-1]:
            args.outprefix = f"{args.outprefix}."
    if 0 != len(args.outsuffix):
        if '.' != args.outsuffix[0]:
            args.outsuffix = f".{args.outsuffix}"

    assert 1 == args.neighbour % 2
    assert args.min_Z >= 0 and args.min_Z <= 1

    args.combineWith2D = args.mask_2d is not None
    if args.combineWith2D:
        assert os.path.isdir(args.mask_2d
            ), f"2D mask folder not found, '{args.mask_2d}'"

    args.threads = check_threads(args.threads)

    return args

def print_settings(args: argparse.Namespace, clear: bool = True) -> str:
    s = f"""
# Automatic 3D segmentation v{args.version}

---------- SETTING :  VALUE ----------

   Input directory :  '{args.input}'
  Output directory :  '{args.output}'

       Mask prefix :  '{args.outprefix}'
       Mask suffix :  '{args.outsuffix}'
     Neighbourhood :  {args.neighbour}
          2D masks : '{args.mask_2d}'
           Labeled :  {args.labeled}
        Compressed :  {args.compressed}

 Dilate-fill-erode :  {args.dilate_fill_erode}
 Minimum Z portion :  {args.min_Z:.2f}
    Minimum radius :  [{args.radius[0]:.2f}, {args.radius[1]:.2f}] vx
           Clear Z :  {args.do_clear_Z}

           Threads :  {args.threads}
            Regexp :  {args.inreg.pattern}
             Debug :  {args.debug_mode}

    """
    if clear: print("\033[H\033[J")
    print(s)
    return(s)

def confirm_arguments(args: argparse.Namespace) -> None:
    settings_string = print_settings(args)
    if not args.do_all: ask("Confirm settings and proceed?")

    assert os.path.isdir(args.input
        ), f"image folder not found: {args.input}"
    if not os.path.isdir(args.output): os.mkdir(args.output)

    with open(os.path.join(args.output, "settings.txt"), "w+") as OH:
        export_settings(OH, settings_string)

def run_segmentation(args: argparse.Namespace,
    imgpath: str, imgdir: str) -> None:
    I = Image.from_tiff(os.path.join(imgdir, imgpath))
    logging.info(f"Image axes: {I.axes}")
    logging.info(f"Image shape: {I.shape}")
    I.rescale_factor = I.get_huygens_rescaling_factor()
    logging.info(f"Rescaling factor: {I.rescale_factor}")

    binarizer = segmentation.Binarizer()
    binarizer.segmentation_type = const.SegmentationType.THREED
    binarizer.local_side = args.neighbour
    binarizer.min_z_size = args.min_Z
    binarizer.do_clear_Z_borders = args.do_clear_Z

    mask2d = None
    if args.combineWith2D:
        if os.path.isdir(args.manual_2d_masks):
            mask2_path = os.path.join(
                args.manual_2d_masks, os.path.basename(imgpath))
            if os.path.isfile(mask2d_path):
                mask2d = ImageLabeled.from_tiff(mask2_path, axes="YX",
                    doRelabel=False)

    M = binarizer.run(I, mask2d)

    if 0 != args.dilate_fill_erode:
        logging.info("dilating")
        M.dilate(args.dilate_fill_erode)
        logging.info("filling")
        M.fill_holes()
        logging.info("eroding")
        M.erode(args.dilate_fill_erode)
    logging.info("labeling")
    L = M.label()

    xy_size_range = (np.pi*args.radius[0]**2, np.pi*args.radius[1]**2)
    logging.info(f"filtering XY size: {xy_size_range}")
    L.filter_size("XY", xy_size_range)
    z_size_range = (args.min_Z*I.axis_shape("Z"), np.inf)
    logging.info(f"filtering Z size: {z_size_range}")
    L.filter_size("Z", z_size_range)

    if mask2d is not None:
        logging.info("recovering labels from 2D mask")
        L.inherit_labels(mask2d)

    imgbase,imgext = os.path.splitext(imgpath)
    if not args.labeled:
        logging.info("writing binary output")
        M = ImageBinary(L.pixels)
        M.to_tiff(os.path.join(args.output,
            f"{args.outprefix}{imgbase}{args.outsuffix}{imgext}"),
            args.compressed)
    else:
        logging.info("writing labeled output")
        L.to_tiff(os.path.join(args.output,
            f"{args.outprefix}{imgbase}{args.outsuffix}{imgext}"),
            args.compressed)

def run(args: argparse.Namespace) -> None:
    imglist = [f for f in os.listdir(args.input) 
        if os.path.isfile(os.path.join(args.input, f))
        and not type(None) == type(re.match(args.inreg, f))]
    
    if 0 != len(args.outsuffix): imglist = [f for f in imglist
        if not os.path.splitext(f)[0].endswith(args.outsuffix)]
    if 0 != len(args.outprefix): imglist = [f for f in imglist
        if not os.path.splitext(f)[0].startswith(args.outprefix)]
    
    logging.info(f"found {len(imglist)} image(s) to segment.")
    if 1 == args.threads:
        for imgpath in tqdm(imglist): run_segmentation(
            args, imgpath, args.input)
    else:
        Parallel(n_jobs = args.threads, verbose = 11)(
            delayed(run_segmentation)(
                args, imgpath, args.input)
            for imgpath in imglist)

def main():
    args = parse_arguments()
    if args.debug_mode: logging.getLogger().level = logging.DEBUG
    confirm_arguments(args)
    run(args)
