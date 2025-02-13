"""
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
"""

import itertools
import joblib  # type: ignore
import logging
import numpy as np  # type: ignore
import os
import pandas as pd  # type: ignore
from radiantkit.distance import RadialDistanceCalculator
from radiantkit.channel import ImageGrayScale
from radiantkit.image import Image, ImageBinary, ImageLabeled, offset2
from radiantkit.selection import BoundingElement
from radiantkit.stat import cell_cycle_fit, range_from_fit
from rich.progress import track  # type: ignore
from skimage.measure import marching_cubes_lewiner  # type: ignore
from skimage.measure import mesh_surface_area
from skimage.morphology import convex_hull_image  # type: ignore
from typing import Any, Dict, List, Optional, Tuple, Type
from skimage.filters import threshold_otsu #ADDED



class ParticleBase(ImageBinary):
    _region_of_interest: BoundingElement
    idx: Optional[int] = None
    _total_size: Optional[int] = None
    _surface: Optional[int] = None

    def __init__(
        self,
        pixels: np.ndarray,
        roi: BoundingElement,
        axes: Optional[str] = None,
    ):
        assert pixels.shape == roi.shape, (pixels.shape, roi)
        super(ParticleBase, self).__init__(pixels, None, axes)
        self._region_of_interest = roi

    @property
    def roi(self) -> BoundingElement:
        return self._region_of_interest

    @property
    def total_size(self) -> int:
        if self._total_size is None:
            self._total_size = self.foreground
        return self._total_size

    @property
    def volume(self) -> int:
        return int(self.total_size * np.prod(self.aspect))

    @property
    def surface(self) -> float:
        if self._surface is None:
            verts, faces, ns, vs = marching_cubes_lewiner(
                self.offset(1), 0.0, self.aspect
            )
            self._surface = mesh_surface_area(verts, faces)
        return self._surface

    def shape_descriptor(self) -> float:
        if 2 == len(self.shape):
            convex_size = convex_hull_image(self._pixels).sum()
            return self.total_size / convex_size
        elif 3 == len(self.shape):
            sphere_surface = (np.pi * (6.0 * self.total_size) ** 2) ** (1 / 3.0)
            return sphere_surface / self.surface
        else:
            return 0.0

    def axis_size(self, axes_to_measure: str) -> int:
        assert all([axis in self.axes for axis in axes_to_measure])
        axes_idxs = tuple(
            [self.axes.index(a) for a in self.axes if a not in axes_to_measure]
        )
        return int(self._pixels.max(axes_idxs).sum())

    def offset_class(self, offset: int) -> "ParticleBase":
        pixels = offset2(self.pixels, offset)
        particle = type(self)(pixels, self.roi.offset(offset), self.axes)
        particle.aspect = self.aspect
        return particle

    def from_this(self, pixels: np.ndarray, keepPath: bool = False) -> "ParticleBase":
        I2 = type(self)(pixels, self.roi, self.axes)
        I2.aspect = self.aspect
        return I2


class Particle(ParticleBase):
    _intensity: Dict[str, Dict[str, float]]
    source: str

    def __init__(
        self,
        pixels: np.ndarray,
        roi: BoundingElement,
        axes: Optional[str] = None,
    ):
        super(Particle, self).__init__(pixels, roi, axes)
        self._intensity = {}

    @property
    def channel_names(self):
        return list(self._intensity.keys())

    def get_intensity_sum(self, channel_name: str) -> Optional[float]:
        if channel_name in self._intensity:
            return self._intensity[channel_name]["sum"]
        else:
            return np.nan

    def get_intensity_mean(self, channel_name: str) -> Optional[float]:
        if channel_name in self._intensity:
            return self._intensity[channel_name]["mean"]
        else:
            return np.nan

    def init_intensity_features(
        self, img: ImageGrayScale, channel_name: str = "unknown"
    ) -> None:
        if channel_name in self._intensity:
            logging.warning(f"overwriting intensity mean of channel '{channel_name}'.")
        else:
            self._intensity[channel_name] = {}

        pixels = self._region_of_interest.apply(img)[self.pixels]
        if img.background is not None:
            pixels -= img.background
        self._intensity[channel_name]["mean"] = float(np.mean(pixels))
        self._intensity[channel_name]["sum"] = np.sum(pixels)

    def get_intensity_value_counts(self, img: ImageGrayScale) -> List[np.ndarray]:
        pixels = self._region_of_interest.apply(img)[self.pixels]
        img.unload()
        if img.background is not None:
            pixels -= img.background
        odata = pd.DataFrame(np.unique(pixels, return_counts=True)).transpose()
        odata.columns = ["value", "count"]
        odata.set_index("value")
        return odata


class Nucleus(Particle):
    _center_dist: Optional[np.ndarray] = None
    _lamina_dist: Optional[np.ndarray] = None

    def __init__(
        self,
        pixels: np.ndarray,
        roi: BoundingElement,
        axes: Optional[str] = None,
    ):
        super(Nucleus, self).__init__(pixels, roi, axes)

    @property
    def distances(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        return (self._center_dist, self._lamina_dist)

    def has_distances(self) -> bool:
        return self._lamina_dist is not None and self._center_dist is not None

    def init_distances(
        self, rdc: RadialDistanceCalculator, C: Optional[Image] = None
    ) -> None:
        distances = rdc.calc(self, C)
        assert distances is not None
        self._lamina_dist, self._center_dist = distances

    def get_intensity_at_distance( #CHANGED
        self, img: ImageGrayScale, img2: ImageGrayScale, ref: Optional[ImageGrayScale] = None
    ) -> pd.DataFrame:
        assert self._lamina_dist is not None and self._center_dist is not None
        
        #ADDED
        global_threshold = threshold_otsu(img2.pixels)
        img2_segment = img.threshold_global(global_threshold) #makes true or false!!

        df = pd.DataFrame.from_dict(
            dict(
                ivalue=self._region_of_interest.apply(img)[self.pixels],
                lamina_dist=self._lamina_dist[self.pixels],
                ivalue_tmr = self._region_of_interest.apply(img2_segment)[self.pixels], #ADDED
                center_dist=self._center_dist[self.pixels],
            )
        )

        df["lamina_dist_norm"] = df["lamina_dist"] / (
            df["lamina_dist"] + df["center_dist"]
        )
        df["nucleus_label"] = self.idx

        if ref is not None:
            ref_value = self._region_of_interest.apply(ref)[self.pixels]
            df["ivalue_norm"] = df["ivalue"].values / ref_value

        return df


class NucleiList(object):
    def __init__(self, nuclei: List[Nucleus]):
        super(NucleiList, self).__init__()
        self.__nuclei = nuclei

    @property
    def nuclei(self):
        return self.__nuclei.copy()

    @staticmethod
    def from_field_of_view(
        maskpath: str, rawpath: str, do_rescale: bool = True
    ) -> "NucleiList":
        img = ImageGrayScale.from_tiff(rawpath, do_rescale=do_rescale)
        mask = ImageBinary.from_tiff(maskpath)
        assert img.shape == mask.shape

        nuclei = ParticleFinder().get_particles_from_binary_image(mask, Nucleus)
        for nucleus in nuclei:
            nucleus.init_intensity_features(img)
            nucleus.source = rawpath

        return NucleiList(nuclei)

    @staticmethod
    def from_multiple_fields_of_view(
        masklist: List[Tuple[str, str]],
        ipath: str,
        do_rescale: bool = True,
        threads: int = 1,
    ) -> "NucleiList":
        if 1 == threads:
            nuclei = []
            for rawpath, maskpath in track(masklist):
                nuclei.append(
                    NucleiList.from_field_of_view(
                        os.path.join(ipath, maskpath),
                        os.path.join(ipath, rawpath),
                        do_rescale,
                    )
                )
        else:
            nuclei = joblib.Parallel(n_jobs=threads, verbose=11)(
                joblib.delayed(NucleiList.from_field_of_view)(
                    os.path.join(ipath, maskpath),
                    os.path.join(ipath, rawpath),
                    do_rescale,
                )
                for rawpath, maskpath in masklist
            )

        return NucleiList.concat(nuclei)

    @staticmethod
    def concat(lists: List["NucleiList"]) -> "NucleiList":
        return NucleiList(list(itertools.chain(*[nl.nuclei for nl in lists])))

    def __len__(self):
        return len(self.__nuclei)

    def get_data(self):
        ndata = pd.DataFrame.from_dict(
            dict(
                image=[n.source for n in self.nuclei],
                label=[n.idx for n in self.nuclei],
                size=[n.total_size for n in self.nuclei],
            )
        )
        channels = list(set(itertools.chain(*[n.channel_names for n in self.nuclei])))
        for channel in channels:
            ndata[f"isum_{channel}"] = [
                n.get_intensity_sum(channel) for n in self.nuclei
            ]
        return ndata

    def select_G1(
        self, k_sigma: float = 2.5, channel: str = "unknown"
    ) -> Tuple[pd.DataFrame, Dict[str, Dict[str, Any]]]:
        ndata = self.get_data()
        isum_label = f"isum_{channel}"

        size_fit = cell_cycle_fit(ndata["size"].values)
        assert size_fit[0] is not None
        size_range = range_from_fit(ndata["size"].values, *size_fit, k_sigma)
        assert size_range is not None

        isum_fit = cell_cycle_fit(ndata[isum_label].values)
        assert isum_fit[0] is not None
        isum_range = range_from_fit(ndata[isum_label].values, *isum_fit, k_sigma)
        assert isum_range is not None

        ndata["pass_size"] = np.logical_and(
            ndata["size"].values >= size_range[0], ndata["size"].values <= size_range[1]
        )
        ndata["pass_isum"] = np.logical_and(
            ndata[isum_label].values >= isum_range[0],
            ndata[isum_label].values <= isum_range[1],
        )
        ndata["pass"] = np.logical_and(ndata["pass_size"], ndata["pass_isum"])
        ndata["ref"] = channel

        return (
            ndata,
            dict(
                size=dict(range=size_range, fit=size_fit),
                isum=dict(range=isum_range, fit=isum_fit),
            ),
        )


class ParticleFinder(object):
    def __init__(self):
        super(ParticleFinder, self).__init__()

    @staticmethod
    def get_particles_from_binary_image(
        B: ImageBinary, particleClass: Type[Particle] = Particle
    ) -> List[Any]:
        return ParticleFinder.get_particles_from_labeled_image(B.label(), particleClass)

    @staticmethod
    def get_particles_from_labeled_image(
        L: ImageLabeled, particleClass: Type[Particle] = Particle
    ) -> List[Any]:
        assert L.pixels.min() != L.pixels.max(), "monochromatic image detected."

        boxed_particles: List[Particle] = []
        for particle_label in np.unique(L.pixels):
            if 0 == particle_label:
                continue
            binary_pixels = L.pixels == particle_label
            roi = BoundingElement.from_binary_pixels(binary_pixels)
            particle = particleClass(roi.apply_to_pixels(binary_pixels), roi, L.axes)
            particle.aspect = L.aspect
            particle.idx = particle_label
            boxed_particles.append(particle)
        return boxed_particles
