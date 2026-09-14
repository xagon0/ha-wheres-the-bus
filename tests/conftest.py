import importlib.util
import pathlib
import sys

# HACS deploys this repository root as custom_components/wheresthebus.
root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wheresthebus', root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec)
sys.modules['wheresthebus'] = module
spec.loader.exec_module(module)
