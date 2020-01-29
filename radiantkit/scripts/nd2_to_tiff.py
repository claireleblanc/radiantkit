'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

import argparse
import logging
import os
import pims
from radiantkit.conversion import ND2Reader2
import radiantkit.image as imt
from radiantkit.string import MultiRange
from radiantkit.string import TIFFNameTemplateFields as TNTFields
from radiantkit.string import TIFFNameTemplate as TNTemplate
import sys
from tqdm import tqdm
from typing import List, Optional

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S')

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = f'''
Convert a nd2 file into single channel tiff images. In the case of 3+D images,
the script also checks for consistent deltaZ distance across consecutive 2D
slices (i.e., dZ). If the distance is consitent, it is used to set the tiff
image dZ metadata. Otherwise, the script stops. Use the -Z argument to disable
this check and provide a single dZ value to be used.

The output tiff file names follow the specified template (-T). A template is a
string including a series of "seeds" that are replaced by the corresponding
values when writing the output file. Available seeds are:
{TNTFields.CHANNEL_NAME} : channel name, lower-cased.
{TNTFields.CHANNEL_ID} : channel ID (number).
{TNTFields.SERIES_ID} : series ID (number).
{TNTFields.DIMENSIONS} : number of dimensions, followed by "D".
{TNTFields.AXES_ORDER} : axes order (e.g., "TZYX").
Leading 0s are added up to 3 digits to any ID seed.

The default template is "{TNTFields.CHANNEL_NAME}_{TNTFields.SERIES_ID}".
Hence, when writing the 3rd series of the "a488" channel, the output file name
would be:"a488_003.tiff".

Please, remember to escape the "$" when running from command line if using
double quotes, i.e., "\\$". Alternatively, use single quotes, i.e., '$'.
    ''', formatter_class = argparse.RawDescriptionHelpFormatter)

    parser.add_argument('input', type = str,
        help = '''Path to the nd2 file to convert.''')

    parser.add_argument('-o', '--outdir', metavar = "outdir", type = str,
        help = """Path to output TIFF folder, created if missing. Default to a
        folder with the input file basename.""", default = None)
    parser.add_argument('-Z', '--deltaZ', type = float, metavar = 'dZ',
        help = """If provided (in um), the script does not check delta Z
        consistency and instead uses the provided one.""", default = None)
    parser.add_argument('-T', '--template', metavar = "template", type = str,
        help = f"""Template for output file name. See main description for more
        details. Default: '{TNTFields.CHANNEL_NAME}_{TNTFields.SERIES_ID}'""",
        default = f"{TNTFields.CHANNEL_NAME}_{TNTFields.SERIES_ID}")
    parser.add_argument('-f', '--fields', metavar = "fields", type = str,
        help = """Extract only specified fields of view. Can be specified as
        when specifying which pages to print. E.g., '1-2,5,8-9'.""",
        default = None)
    parser.add_argument('-c', '--channels', metavar = "channels", type = str,
        help = """Extract only specified channels. Should be specified as a list
        of space-separated channel names. E.g., 'dapi cy5 a488'.""",
        default = None, nargs = "+")

    parser.add_argument('-C', '--compressed',
        action = 'store_const', dest = 'doCompress',
        const = True, default = False,
        help = 'Force compressed TIFF as output.')
    parser.add_argument('-n', '--dry-run',
        action = 'store_const', dest = 'dry',
        const = True, default = False,
        help = 'Describe input data and stop.')

    version = "0.0.1"
    parser.add_argument('--version', action = 'version',
        version = f'{sys.argv[0]} {version}')

    args = parser.parse_args()

    if args.outdir is None:
        args.outdir = os.path.splitext(os.path.basename(args.input))[0]
        args.outdir = os.path.join(os.path.dirname(args.input), args.outdir)

    assert os.path.isfile(args.input), f"input file not found: {args.input}"
    assert not os.path.isfile(args.outdir
        ), f"output directory cannot be a file: {args.outdir}"
    if not os.path.isdir(args.outdir): os.mkdir(args.outdir)

    if args.fields is not None:
        args.fields = MultiRange(args.fields)
        args.fields.zero_indexed = True

    if args.channels is not None:
        args.channels = [c.lower() for c in args.channels]

    assert 0 != len(args.template)
    args.template = TNTemplate(args.template)

    return args

def get_output_path(args: argparse.Namespace, bundle_axes: List[str],
    metadata: dict, channel_id: int, field_id: int) -> str:
    d = {
        'channel_name' : metadata['channels'][channel_id].lower(),
        'channel_id' : f"{(channel_id+1):03d}",
        'series_id' : f"{(field_id+1):03d}",
        'dimensions' : len(bundle_axes),
        'axes_order' : "".join(bundle_axes)
    }
    return f"{args.template.safe_substitute(d)}.tiff"

def export_channel(args: argparse.Namespace, field_of_view: pims.frame.Frame,
    opath: str, metadata: dict, bundle_axes: List[str],
    resolutionZ: float = None) -> None:
    resolutionXY = (1/metadata['pixel_microns'], 1/metadata['pixel_microns'])
    imt.save_tiff(os.path.join(args.outdir, opath), field_of_view,
        imt.get_dtype(field_of_view.max()), args.doCompress,
        resolution = resolutionXY, inMicrons = True, ResolutionZ = resolutionZ)

def export_field_3d(args: argparse.Namespace, field_of_view: pims.frame.Frame,
    metadata: dict, field_id: int, bundle_axes: List[str],
    channels: List[str] = None) -> None:
    if args.deltaZ is not None: resolutionZ = args.deltaZ
    else: resolutionZ = ND2Reader2.get_resolutionZ(args.input, field_id)

    if "c" not in bundle_axes:
        opath = get_output_path(args, bundle_axes, metadata, 0, field_id)
        export_channel(args, field_of_view, opath, metadata,
            bundle_axes, resolutionZ)
    else:
        if channels is None:
            channels = [c.lower() for c in metadata['channels']]
        for channel_id in range(field_of_view.shape[3]):
            if not metadata['channels'][channel_id].lower() in channels:
                continue
            opath = get_output_path(args, bundle_axes,
                metadata, channel_id, field_id)
            export_channel(args, field_of_view[:, :, :, channel_id], opath,
                metadata, bundle_axes, resolutionZ)

def export_field_2d(args: argparse.Namespace, field_of_view: pims.frame.Frame,
    metadata: dict, field_id: int, bundle_axes: List[str],
    channels: List[str] = None) -> None:
    if "c" not in bundle_axes:
        opath = get_output_path(args, bundle_axes, metadata, 0, field_id)
        export_channel(args, field_of_view, opath, metadata, bundle_axes)
    else:
        if channels is None:
            channels = [c.lower() for c in metadata['channels']]
        for channel_id in range(field_of_view.shape[3]):
            if not metadata['channels'][channel_id].lower() in channels:
                continue
            opath = get_output_path(args, metadata, channel_id, field_id)
            export_channel(args, field_of_view[:, :, channel_id],
                opath, metadata, bundle_axes)

def log_nd2_info(nd2I: ND2Reader2) -> None:
    logging.info(f"Found {nd2I.field_count()} field(s) of view, " +
        f"with {nd2I.channel_count()} channel(s).")
    logging.info(f"Channels: {list(nd2I.get_channel_names())}.")
    if nd2I.is3D: logging.info("XYZ size: " + 
        f"{nd2I.sizes['x']} x {nd2I.sizes['y']} x {nd2I.sizes['z']}")
    else: logging.info(f"XY size: {nd2I.sizes['x']} x {nd2I.sizes['y']}")

def clean_channel_list(nd2I: ND2Reader2,
    channels: Optional[List[str]]) -> Optional[List[str]]:
    if channels is not None:
        channels = [c for c in channels
            if c in list(nd2I.get_channel_names())]
        if 0 == len(channels):
            logging.error("None of the specified channels was found.")
            sys.exit()
        logging.info(f"Converting only the following channels: {channels}")
    return channels

def run(args: argparse.Namespace) -> None:
    if args.deltaZ is not None:
        logging.info(f"Enforcing a deltaZ of {args.deltaZ:.3f} um.")

    nd2I = ND2Reader2(args.input)
    assert not nd2I.isLive(), "time-course conversion images not implemented."
    log_nd2_info(nd2I)
    if args.dry: sys.exit()

    if not args.template.can_export_fields(nd2I.field_count(), args.fields):
        logging.critical("when exporting more than 1 field, the template " +
            f"must include the {TNTFields.SERIES_ID} seed. " +
            f"Got '{args.template.template}' instead.")
        sys.exit()

    logging.info(f"Output directory: '{args.outdir}'")
    if not os.path.isdir(args.outdir): os.mkdir(args.outdir)

    args.channels = clean_channel_list(nd2I, args.channels)
    if not args.template.can_export_channels(
        nd2I.channel_count(), args.channels):
        logging.critical("when exporting more than 1 channel, the template " +
            f"must include either {TNTFields.CHANNEL_ID} or " +
            f"{TNTFields.CHANNEL_NAME} seeds. " +
            f"Got '{args.template.template}' instead.")
        sys.exit()

    export_fn = export_field_3d if nd2I.is3D() else export_field_2d
    if 1 == nd2I.field_count():
        if args.fields is not None:
            if not 1 in list(args.fields):
                logging.warning("Skipped only available field " +
                    "(not included in specified field range.")
        nd2I.set_axes_for_bundling()
        export_fn(args, nd2I[0], nd2I.metadata, 0, nd2I.bundle_axes,
            args.channels)
    else:
        nd2I.iter_axes = 'v'
        nd2I.set_axes_for_bundling()

        if args.fields is not None:
            args.fields = list(args.fields)
            logging.info("Converting only the following fields: " +
                f"{[x for x in args.fields]}")
            field_generator = tqdm(args.fields)
        else: field_generator = tqdm(range(nd2I.sizes['v']))

        for field_id in field_generator:
            if field_id-1 >= nd2I.field_count():
                logging.warning(f"Skipped field #{field_id}" +
                    "(from specified field range, not available in nd2 file).")
            else:
                export_fn(args, nd2I[field_id-1], nd2I.metadata,
                    field_id-1, nd2I.bundle_axes, args.channels)

def main():
    run(parse_arguments())
