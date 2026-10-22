import sys
import yaml
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds  


NON_STOCHASTIC_NAME = '1'


def is_stochastic(case=None) -> bool:
    """
    If the switches in the provided case specify a path to a stochastic config file,
    we're using stochastic optimization; if not, we're not.
    """
    sw = reeds.io.get_switches(reeds.io.standardize_case(case))
    return (sw.GSw_Stochastic != '0')


def get_config_path(case):
    """
    If specified case uses stochastic optimization, return the path to its stochastic config file.
    If it does not use stochastic optimization, return None.
    Allowable keywords (encased in {curly brackets}) are:
        {reeds_path} and {reedspath}: Resolve to the path of the active ReEDS repo
        {inputs}: Resolves to {reeds_path}/inputs
    """
    sw = reeds.io.get_switches(reeds.io.standardize_case(case))
    if sw.GSw_Stochastic == '0':
        spath = None
    else:
        spath = Path(
            sw.GSw_Stochastic.format(
                reeds_path=reeds.io.reeds_path,
                reedspath=reeds.io.reeds_path,
                inputs=str(Path(reeds.io.reeds_path, 'inputs')),
            )
        )
    return spath


def _get_config(case) -> dict:
    """Load config file without validating"""
    spath = get_config_path(case)
    if not spath.is_file():
        raise FileNotFoundError(spath)
    if spath.suffix not in ['.yaml', '.yml']:
        raise ValueError(f'Provided {spath} but must be a yaml file')
    with open(spath, 'r') as f:
        config = yaml.safe_load(f)
    return config


def validate_config(case):
    """
    Args:
        case: A path to either a ReEDS case or a stochastic config file
    """
    if not Path(case).exists():
        raise FileNotFoundError(case)
    elif Path(case).is_dir():
        config = _get_config(case)
        spath = get_config_path(case)
    elif Path(case).suffix in ['.yaml', '.yml']:
        spath = case
        with open(spath, 'r') as f:
            config = yaml.safe_load(f)

    ## Required keys must be included
    required = ['scenario_probability', 'scenario_switches']
    for key in required:
        if key not in config:
            raise ValueError(f'{key} must be a top-level key in {spath}')
    ## No other keys must be included
    for key in config:
        if key not in required:
            raise ValueError(f'{spath}: {key} is invalid; the allowed keys are {required}')
    ## The same scenario names must be used in each key
    scens_probability = set(config['scenario_probability'].keys())
    scens_switches = set(config['scenario_switches'].keys())
    if scens_probability != scens_switches:
        err = (
            'The same scenario names must be used for scenario_probability and '
            f'scenario_switches.\nIn {spath}, the scenario names are:\n'
            f'scenario_probability: {scens_probability}\n'
            f'scenario_switches: {scens_switches}\n'
        )
        raise ValueError(err)


def get_config(case) -> dict:
    """Load, validate, and return config"""
    validate_config(case)
    return _get_config(case)


def get_scenarios(case) -> list:
    """Return list of stochastic scenarios used in case"""
    if not is_stochastic(case):
        scenarios = [NON_STOCHASTIC_NAME]
    else:
        config = get_config(case)
        scenarios = list(config['scenario_probability'].keys())
    return scenarios


def get_probabilities(case) -> dict:
    """Weight scenario probabilities to sum to 1"""
    if is_stochastic(case):
        config = get_config(case)
        probs_in = config['scenario_probability']
        total_prob = sum(probs_in.values())
        probs_out = {key: val / total_prob for key, val in probs_in.items()}
    else:
        probs_out = {NON_STOCHASTIC_NAME: 1}
    return probs_out
