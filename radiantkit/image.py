'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

import logging
import numpy as np
import os
from radiantkit import const
from skimage import filters
from skimage.io import imread
from skimage.measure import label
from skimage.morphology import square, cube
from skimage.morphology import closing, opening
from skimage.morphology import dilation, erosion
from skimage.segmentation import clear_border
import tifffile
from typing import List, Tuple, Union
import warnings

class ImageSettings(object):
    _axes_order: str = "TZYX"

    def __init__(self):
        super(ImageSettings, self).__init__()
    
    @property
    def nd(self) -> int:
        return len(self._axes_order)

class ImageBase(ImageSettings):
    _path_to_local: str = None
    _pixels: np.ndarray = None

    def __init__(self, pixels: np.ndarray, path: str=None):
        super(ImageSettings, self).__init__()
        self._pixels = pixels.copy()
        self._extract_nd()

    @property
    def shape(self) -> Tuple[int]:
        return self._pixels.shape

    @property
    def pixels(self) -> np.ndarray:
        if self._pixels is None and self._path_to_local is not None:
            self.load_from_local()
        return self._pixels

    @property
    def dtype(self) -> str:
        return get_dtype(self.pixels.max())

    @staticmethod
    def from_tiff(path: str) -> 'ImageBase':
        return ImageBase(read_tiff(path), path)
    
    def _extract_nd(self) -> None:
        self._pixels = extract_nd(self._pixels, self.nd)
        if len(self._pixels.shape) != self.nd:
            self._axes_order = self._axes_order[-self.nd:]

    def z_project(self, projection_type: const.ProjectionType) -> np.ndarray:
        return z_project(self.pixels, projection_type)

    def load_from_local(self) -> None:
        assert self._path_to_local is not None
        assert os.path.isfile(self._path_to_local)
        self.from_tiff(self._path_to_local)

    def unload(self) -> None:
        if self._path_to_local is None:
            logging.error("cannot unload Image without path_to_local.")
            return
        if not os.path.isfile(self._path_to_local):
            logging.error("path_to_local not found, cannot unload: " +
                self._path_to_local)
            return
        self._pixels = None

    def to_tiff(self, path: str, compressed: bool, inMicrons: bool=False,
        ResolutionZ: float=None, forImageJ: bool=False, **kwargs) -> None:
        save_tiff(path, self.pixels, self.dtype, compressed, inMicrons,
            ResolutionZ, forImageJ, **kwargs)

class ImageLabeled(ImageBase):
    def __init__(self, pixels: np.ndarray, path: str=None,
        doRelabel: bool=True):
        super(ImageLabeled, self).__init__(pixels, path)
        if doRelabel: self._relabel()

    @staticmethod
    def from_tiff(self, path: str, doRelabel: bool=True) -> 'ImageLabeled':
        return ImageLabeled(read_tiff(path), path, doRelabel)

    def _relabel(self) -> None:
        self._pixels = self._pixels.copy() > self._pixels.min()
        self._pixels = label(self._pixels)

    def clear_XY_borders(self) -> None:
        self._pixels = clear_XY_borders(self._pixels)

    def clear_Z_borders(self) -> None:
        self._pixels = clear_Z_borders(self._pixels)

class ImageLabeled2D(ImageLabeled):
    _axes_order: str = "YX"
    def __init__(self, pixels: np.ndarray, path: str=None,
        doRelabel: bool=True):
        super(Image3D, self).__init__(pixels, path, doRelabel)

    @staticmethod
    def from_tiff(self, path: str, doRelabel: bool=True) -> 'ImageLabeled2D':
        return ImageLabeled2D(read_tiff(path), path, doRelabel)

class ImageLabeled3D(ImageLabeled):
    _axes_order: str = "ZYX"
    def __init__(self):
        super(Image3D, self).__init__()

    @staticmethod
    def from_tiff(self, path: str, doRelabel: bool=True) -> 'ImageLabeled3D':
        return ImageLabeled3D(read_tiff(path), path, doRelabel)

class ImageBinary(ImageBase):
    def __init__(self, pixels: np.ndarray, path: str=None,
        doRebinarize: bool=True):
        super(ImageBinary, self).__init__(pixels, path)
        if doRebinarize: self._rebinarize()
        assert 1 == self._pixels.max()

    @staticmethod
    def from_tiff(self, path: str, doRebinarize: bool=True) -> 'ImageBinary':
        return ImageBinary(read_tiff(path), path, doRebinarize)

    def _rebinarize(self) -> None:
        self._pixels = self._pixels > self._pixels.min()

    def fill_holes(self) -> None:
        self._pixels = fill_holes(self._pixels)

    def close(self) -> None:
        self._pixels = closing2(self._pixels)

    def open(self) -> None:
        self._pixels = opening2(self._pixels)

    def dilate(self) -> None:
        self._pixels = dilate(self._pixels)

    def erode(self) -> None:
        self._pixels = erode(self._pixels)

    def logical_and(self, B: 'ImageBinary') -> None:
        self._pixels = np.logical_and(self._pixels, B.pixels)

    def logical_or(self, B: 'ImageBinary') -> None:
        self._pixels = np.logical_or(self._pixels, B.pixels)

    def logical_xor(self, B: 'ImageBinary') -> None:
        self._pixels = np.logical_xor(self._pixels, B.pixels)

    def invert(self) -> None:
        self._pixels = np.logical_not(self._pixels)

    def label(self) -> ImageLabeled:
        return ImageLabeled(self.pixels)

class ImageBinary2D(ImageBinary):
    _axes_order: str = "YX"
    def __init__(self, pixels: np.ndarray, path: str=None,
        doRebinarize: bool=True):
        super(ImageBinary2D, self).__init__(pixels, path, doRebinarize)

    @staticmethod
    def from_tiff(path: str) -> 'ImageBinary2D':
        return ImageBinary2D(read_tiff(path), path)

class ImageBinary3D(ImageBinary):
    _axes_order: str = "ZYX"
    def __init__(self, pixels: np.ndarray, path: str=None,
        doRebinarize: bool=True):
        super(ImageBinary3D, self).__init__(pixels, path, doRebianrize)

    @staticmethod
    def from_tiff(path: str) -> 'ImageBinary3D':
        return ImageBinary3D(read_tiff(path), path)

class Image(ImageBase):
    __rescale_factor: float = 1.

    def __init__(self, pixels: np.ndarray, path: str=None):
        super(Image, self).__init__(pixels, path)
    
    @property
    def rescale_factor(self) -> float:
        return self._rescale_factor
    
    @rescale_factor.setter
    def rescale_factor(self, new_factor: float) -> None:
        self._pixels = self.pixels*self.rescale_factor
        self.__rescale_factor = new_factor
        self._pixels = self.pixels/self.rescale_factor

    @staticmethod
    def from_tiff(path: str) -> 'Image':
        return Image(read_tiff(path), path)

    def get_huygens_rescaling_factor(self) -> float:
        if self._path_to_local is None: return 1.
        return get_huygens_rescaling_factor(self._path_to_local)

    def threshold_global(self, thr: Union[int,float]) -> ImageBinary:
        return ImageBinary.from_tiff(self.pixels>thr, doRebinarize=False)

    def threshold_adaptive(self, block_size: int,
        method: str, mode: str, *args, **kwargs) -> ImageBinary:
        return ImageBinary(threshold_adaptive(self.pixels, block_size,
            method, mode, *args, **kwargs), doRebinarize=False)

class Image2D(Image):
    _axes_order: str = "YX"
    def __init__(self, pixels: np.ndarray, path: str=None):
        super(Image2D, self).__init__(pixels, path)

    @staticmethod
    def from_tiff(path: str) -> 'Image2D':
        return Image2D(read_tiff(path), path)

class Image3D(Image):
    _axes_order: str = "ZYX"
    def __init__(self, pixels: np.ndarray, path: str=None):
        super(Image3D, self).__init__(pixels, path)

    @staticmethod
    def from_tiff(path: str) -> 'Image3D':
        return Image3D(read_tiff(path), path)

def get_huygens_rescaling_factor(path: str) -> float:
    basename,ext = tuple(os.path.splitext(os.path.basename(path)))
    path = os.path.join(os.path.dirname(path), f"{basename}_history.txt")
    if not os.path.exists(path): return 1
    needle = 'Stretched to Integer type'
    with open(path, 'r') as fhistory:
        factor = fhistory.readlines()
        factor = [x for x in factor if needle in x]
    if 0 == len(factor): return 1
    elif 1 == len(factor): return float(factor[0].strip().split(' ')[-1])
    else: return np.prod([float(f.strip().split(' ')[-1]) for f in factor])

def get_dtype(imax: Union[int,float]) -> str:
    depths = [8, 16]
    for depth in depths:
        if imax <= 2**depth-1:
            return("uint%d" % (depth,))
    return("uint")

def read_tiff(path: str) -> np.ndarray:
    assert os.path.isfile(path), f"file not found: '{path}'"
    try:
        with warnings.catch_warnings(record=True) as warning_list:
            I = imread(path)
            warning_list = [str(e) for e in warning_list]
            if any(["axes do not match shape" in e for e in warning_list]):
                print(f"WARNING: "+
                    "image axes do not match metadata in '{path}'")
                print("Using the image axes.")
    except (ValueError, TypeError) as e:
        print(f"ERROR: "+
            "cannot read image from '{path}', file seems corrupted.")
        raise
    return I

def extract_nd(I: np.ndarray, nd: int) -> np.ndarray:
    if len(I.shape) <= nd: return I
    while len(I.shape) > nd: I = I[0]
    if 0 in I.shape: print("WARNING: the image contains empty dimensions.")
    return I

def save_tiff(path: str, I: np.ndarray, dtype: str, compressed: bool,
    bundled_axes: str="CZYX", inMicrons: bool=False,
    ResolutionZ: float=None, forImageJ: bool=False, **kwargs) -> None:
    
    if not "C" in bundled_axes: bundled_axes = f"C{bundled_axes}"
    while len(bundled_axes) > len(I.shape):
        new_shape = [1]
        [new_shape.append(n) for n in I.shape]
        I.shape = new_shape

    assert_msg = "shape mismatch between bundled axes and image."
    assert len(bundled_axes) == len(I.shape), assert_msg

    metadata = {'axes' : bundled_axes}
    if inMicrons: metadata['unit'] = "um"
    if not type(None) == ResolutionZ: metadata['spacing'] = ResolutionZ

    if compressed:
        tifffile.imsave(path, I.astype(dtype),
            shape = I.shape, compress = 9,
            dtype = dtype, imagej = forImageJ,
            metadata = metadata, **kwargs)
    else:
        tifffile.imsave(path, I.astype(dtype),
            shape = I.shape, compress = 0,
            dtype = dtype, imagej = forImageJ,
            metadata = metadata, **kwargs)

def z_project(I: np.ndarray,
    projection_type: const.ProjectionType) -> np.ndarray:
    if projection_type == const.ProjectionType.SUM_PROJECTION:
        I = I.sum(0).astype(I.dtype)
    elif projection_type == const.ProjectionType.MAX_PROJECTION:
        I = I.max(0).astype(I.dtype)
    return I

def threshold_adaptive(I: np.ndarray, block_size: int,
    method: str, mode: str, *args, **kwargs) -> np.ndarray:
    assert 0 == block_size % 2

    def threshold_adaptive_slice(I: np.ndarray, block_size: int,
        method: str, mode: str, *args, **kwargs) -> np.ndarray:
        threshold = filters.threshold_local(I, block_size, *args,
            method = method, mode = mode, **kwargs)
        return I >= threshold

    if 2 == len(i.shape):
        mask = threshold_adaptive_slice(I, block_size,
            method, mode, *args, **kwargs)
    elif 3 == len(i.shape):
        mask = I.copy()
        for slice_id in range(mask.shape[0]):
            mask[slice_id, :, :] = threshold_adaptive_slice(
                mask[slice_id, :, :], block_size, method, mode,
                *args, **kwargs)
    else:
        logging.info("Local threshold not implemented for images with " +
            f"{len(I.shape)} dimensions.")
    return mask

def fill_holes(mask: np.ndarray) -> np.ndarray:
    mask = ndi.binary_fill_holes(mask)
    if 3 == len(mask.shape):
        for slice_id in range(mask.shape[0]):
            mask[slice_id, :, :] = ndi.binary_fill_holes(
                mask[slice_id, :, :])
    elif 2 != len(mask.shape):
        logging.warning("3D hole filling not performed on images with " +
            f"{len(mask.shape)} dimensions.")
    return mask

def closing2(mask: np.ndarray) -> np.ndarray:
    assert 1 == mask.max()
    if 2 == len(mask.shape):
        mask = closing(mask, square(3))
    elif 3 == len(i.shape):
        mask = closing(mask, cube(3))
    else:
        logging.info("Close operation not implemented for images with " +
            f"{len(mask.shape)} dimensions.")
    return mask

def opening2(mask: np.ndarray) -> np.ndarray:
    assert 1 == mask.max()
    if 2 == len(mask.shape):
        mask = opening(mask, square(3))
    elif 3 == len(i.shape):
        mask = opening(mask, cube(3))
    else:
        logging.info("Open operation not implemented for images with " +
            f"{len(mask.shape)} dimensions.")
    return mask

def dilate(mask: np.ndarray) -> np.ndarray:
    assert 1 == mask.max()
    if 2 == len(mask.shape):
        mask = dilation(mask, square(3))
    elif 3 == len(i.shape):
        mask = dilation(mask, cube(3))
    else:
        logging.info("Dilate operation not implemented for images with " +
            f"{len(mask.shape)} dimensions.")
    return mask

def erode(mask: np.ndarray) -> np.ndarray:
    assert 1 == mask.max()
    if 2 == len(mask.shape):
        mask = erosion(mask, square(3))
    elif 3 == len(i.shape):
        mask = erosion(mask, cube(3))
    else:
        logging.info("Erode operation not implemented for images with " +
            f"{len(mask.shape)} dimensions.")
    return mask

def clear_XY_borders(L: np.ndarray) -> np.ndarray:
    if 2 == len(L.shape):
        return clear_border(L)
    elif 3 == len(L.shape):
        border_labels = []
        border_labels.extend(np.unique(L[:, 0, :]).tolist())
        border_labels.extend(np.unique(L[:, -1, :]).tolist())
        border_labels.extend(np.unique(L[:, :, 0]).tolist())
        border_labels.extend(np.unique(L[:, :, -1]).tolist())
        border_labels = set(border_labels)
        for lab in border_labels: L[L == lab] = 0
        return label(L)
    else:
        logging.warning("XY border clearing not implemented for images " +
            f"with {len(L.shape)} dimensions.")
        return L

def clear_Z_borders(L: np.ndarray) -> np.ndarray:
    if 2 == len(L.shape): return L
    elif 3 == len(L.shape):
        border_labels = []
        border_labels.extend(np.unique(L[0, :, :]).tolist())
        border_labels.extend(np.unique(L[-1, :, :]).tolist())
        border_labels = set(border_labels)
        for lab in border_labels: L[L == lab] = 0
        return label(L)
    else:
        logging.warning("Z border clearing not implemented for images " +
            f"with {len(L.shape)} dimensions.")
        return L
