'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

from itertools import chain
import logging
from os.path import isfile, join as path_join
from radiantkit.image import Image, ImageBase, ImageBinary, ImageLabeled
from radiantkit.path import find_re, get_image_details
from radiantkit.path import select_by_prefix_and_suffix
from radiantkit.particle import ParticleBase, ParticleFinder, Nucleus
from sys import exit as sys_exit
from typing import Dict, List, Tuple
from typing import Iterator, Optional, Pattern, Type, Union

class SeriesSettings(object):
    _ID: int=0
    _channels: Dict[str, Union[str, Type[Image]]]=None
    _mask: Union[str, Type[Image]]=None
    _ref: Optional[str]=None
    labeled: bool=False

    def __init__(self, ID: int, channel_paths: Dict[str,str],
        mask_path: Optional[str]=None, inreg: Optional[Pattern]=None):
        super(SeriesSettings, self).__init__()
        self._ID = ID

        for name in channel_paths: assert isfile(channel_paths[name])
        self._channels = channel_paths.copy()

        if mask_path is not None:
            ref = get_image_details(mask_path, inreg)[1]
            assert ref in channel_paths
            self._ref = ref
            self._mask = mask_path

    @property
    def ID(self) -> int:
        return self._ID

    @property
    def channel_names(self) -> List[str]:
        return list(self._channels.keys())

    @property
    def channels(self) -> Dict[str, Union[str, Type[Image]]]:
        return self._channels.copy()

    @property
    def ref(self) -> str:
        return self._ref

    @property
    def mask_path(self) -> Optional[str]:
        if isinstance(self._mask, str): return self._mask
        else: return self._mask.path

    @property
    def mask(self) -> Optional[Type[ImageBase]]:
        if self.has_mask():
            if isinstance(self._mask, str): self.init_mask()
            return self._mask

    def has_ref(self) -> bool:
        return self._ref is not None

    def has_mask(self) -> bool:
        return self._mask is not None

    def init_mask(self) -> None:
        if not self.has_mask(): return None
        if isinstance(self._mask, str):
            if self.labeled:
                self._mask = ImageLabeled.from_tiff(self.mask_path)
            else:
                self._mask = ImageBinary.from_tiff(self.mask_path)

    def init_channel(self, channel_name: str) -> None:
        if channel_name in self._channels:
            if isinstance(self._channels[channel_name], str):
                self._channels[channel_name] = Image.from_tiff(
                    self._channels[channel_name])

    def get_channel(self, channel_name: str) -> Optional[Image]:
        if channel_name in self._channels:
            if isinstance(self._channels[channel_name], str):
                self.init_channel(channel_name)
            if isinstance(self._channels[channel_name], Image):
                return self._channels[channel_name]

    def __str__(self) -> str:
        s = f"Series #{self._ID} with {len(self.channel_names)} channels."
        if not self.has_ref(): s += " No reference."
        else:
            s += f" '{self._ref}' reference channel"
            if self.has_mask(): s += " (with mask)"
        for (name, data) in self._channel_data.items():
            s += f"\n  {name} => '{data['path']}'"
        if self.has_mask: s += f"\n  mask => '{self.mask_path}'"
        return s

class Series(SeriesSettings):
    _particles: Optional[List[Type[ParticleBase]]]=None

    def __init__(self, ID: int, channel_paths: Dict[str,str],
        mask_path: Optional[str]=None, inreg: Optional[Pattern]=None):
        super(Series, self).__init__(ID, channel_paths, mask_path, inreg)

    @property
    def particles(self):
        if self._particles is None: logging.warning(
            "particle attribute accessible after running extract_particles.")
        return self._particles
    
    def init_particles(self, channel: Optional[str]=None,
        particleClass: Type[ParticleBase]=Nucleus) -> None:
        if not self.has_mask():
            logging.warning("mask is missing, no particles extracted.")
            return

        if self.labeled:
            fextract = ParticleFinder.get_particles_from_labeled_image
        else: fextract = ParticleFinder.get_particles_from_binary_image
        self._particles = fextract(self.mask, particleClass)
        self.mask.unload()

        for pbody in self._particles: pbody.source = self.mask_path
        if channel is not None:
            assert channel in self.channel_names
            for pbody in self._particles:
                pbody.init_intensity_features(self.get_channel(channel), channel)
            self.get_channel(channel).unload()

    @staticmethod
    def extract_particles(series: 'Series', channel: str,
        particleClass: Type[ParticleBase]) -> 'Series':
        series.init_particles(channel, particleClass)
        return series

    def __str__(self):
        s = super(Series, self).__str__()
        if self._particles is not None:
            s += f"\n  With {len(self._particles)} particles "
            s += f"[{type(self._particles[0]).__name__}]."
        return s

class SeriesList(object):
    _series: List[Series]=None

    def __init__(self, series_list: List[Series]):
        super(SeriesList, self).__init__()
        self._series = series_list

    @property
    def channel_names(self):
        return list(set(chain(*[series.channel_names
            for series in self._series])))

    @staticmethod
    def from_directory(dpath: str, inreg: Pattern, ref: Optional[str]=None,
        maskfix: Optional[Tuple[str, str]]=None):
        channel_list = find_re(dpath, inreg)
        mask_list, channel_list = select_by_prefix_and_suffix(
            dpath, channel_list, *maskfix)
        
        mask_data = {}
        for mask_path in mask_list:
            series_id, channel_name = get_image_details(mask_path,inreg)
            if channel_name != ref:
                logging.warning("skipping mask for channel " +
                    f"'{channel_name}', not reference ({ref}).")
                continue
            if series_id in mask_data:
                logging.warning("found multiple masks for reference channel " +
                    f"in series {series_id}. " +
                    f"Skipping '{mask_path}'.")
                continue
            mask_data[series_id] = path_join(dpath, mask_path)

        channel_data = {}
        for channel_path in channel_list:
            series_id, channel_name = get_image_details(channel_path,inreg)
            if series_id not in channel_data: channel_data[series_id] = {}
            if channel_name in channel_data[series_id]:
                logging.warning("found multiple instances of channel " +
                    f"{channel_name} in series {series_id}. " +
                    f"Skipping '{channel_path}'.")
            channel_data[series_id][channel_name] = path_join(
                dpath, channel_path)

        channel_counts = [len(x) for x in channel_data.values()]
        assert 1 == len(set(channel_counts)), "inconsistent number of channels"

        series_list = []
        for series_id in channel_data.keys():
            if series_id not in mask_data:
                logging.critical("missing mask of reference channel "
                    f"'{ref}' for series '{series_id}'")
                sys_exit()
            series_list.append(Series(series_id,
                channel_data[series_id], mask_data[series_id], inreg))

        return SeriesList(series_list)

    def __len__(self) -> int:
        return len(self._series)

    def __next__(self) -> Series:
        for series in self._series:
            yield series

    def __iter__(self) -> Iterator[Series]:
        return self.__next__()
