import importlib.util
from pathlib import Path


def test_pattern_dictionary_keeps_schema_value_enum():
    path=Path(__file__).resolve().parents[2]/'scripts/tools/export_frontend_types.py'
    spec=importlib.util.spec_from_file_location('frontend_codegen',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    value=module.ts({'type':'object','patternProperties':{'^[a-z][a-z0-9_-]*$':{
        'type':'string','enum':['z_up','y_up']}}})
    assert value=='Record<string, "z_up" | "y_up">'
