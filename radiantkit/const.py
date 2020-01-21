'''
@author: Gabriele Girelli
@contact: gigi.ga90@gmail.com
'''

from enum import auto, Enum

class ProjectionType(Enum):
    SUM_PROJECTION = 'SUM_PROJECTION'
    MAX_PROJECTION = 'MAX_PROJECTION'    

class SegmentationType(ProjectionType):
    SUM_PROJECTION = 'SUM_PROJECTION'
    MAX_PROJECTION = 'MAX_PROJECTION'
    THREED = '3D'
    @staticmethod
    def get_default():
        return SegmentationType.THREED

class AnalysisType(ProjectionType):
    SUM_PROJECTION = 'SUM_PROJECTION'
    MAX_PROJECTION = 'MAX_PROJECTION'
    THREED = '3D'
    MIDSECTION = 'MIDSECTION'
    @staticmethod
    def get_default():
        return AnalysisType.MIDSECTION

class MidsectionType(Enum):
    CENTRAL = 'CENTRAL'
    LARGEST = 'LARGEST'
    MAX_INTENSITY_SUM = 'MAX_INTENSITY_SUM'
    @staticmethod
    def get_default():
        return MidsectionType.LARGEST

class LaminaDistanceType(Enum):
    CENTER_MAX = 'CENTER_MAX'
    CENTER_TOP_QUANTILE = 'CENTER_TOP_QUANTILE'
    DIFFUSION = 'DIFFUSION'
    @staticmethod
    def get_default():
        return LaminaDistanceType.CENTER_TOP_QUANTILE
