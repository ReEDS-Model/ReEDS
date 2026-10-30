import os as _os
import sys as _sys

# numpy's MKL backend finds its kernel DLLs in the env's Library\bin via the
# legacy PATH-based search, which is empty when the env isn't activated at launch.
if _sys.platform == 'win32':
    _dll_dir = _os.path.join(_sys.prefix, 'Library', 'bin')
    if _os.path.isdir(_dll_dir):
        _os.add_dll_directory(_dll_dir)
        if _dll_dir not in _os.environ.get('PATH', ''):
            _os.environ['PATH'] = _dll_dir + _os.pathsep + _os.environ.get('PATH', '')

# openpyxl's lxml backend overrides libxml2's global allocator, corrupting the
# shared libxml2 that GDAL/pyogrio use and crashing map plotting on Windows.
# Import openpyxl once with lxml hidden so it binds the stdlib parser, then
# restore lxml for other consumers (e.g. postprocessing/tableau).
if _sys.platform == 'win32':
    _saved_lxml = {_m: _sys.modules.get(_m) for _m in ('lxml', 'lxml.etree')}
    _sys.modules['lxml'] = None
    _sys.modules['lxml.etree'] = None
    try:
        import openpyxl as _openpyxl  # noqa: F401
    finally:
        for _m, _mod in _saved_lxml.items():
            if _mod is None:
                _sys.modules.pop(_m, None)
            else:
                _sys.modules[_m] = _mod

from . import input_processing as input_processing
from . import core as core
from . import hpc as hpc
from . import resource_adequacy as resource_adequacy

from . import checks as checks
from . import financials as financials
from . import inputs as inputs
from . import io as io
from . import log as log
from . import plots as plots
from . import prasplots as prasplots
from . import reedsplots as reedsplots
from . import remote as remote
from . import report_utils as report_utils
from . import results as results
from . import slurm as slurm
from . import spatial as spatial
from . import techs as techs
from . import timeseries as timeseries
from . import units as units
