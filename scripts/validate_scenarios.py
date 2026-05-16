import json
import pathlib
import sys

import jsonschema


schema = json.loads(
    pathlib.Path("mcpdrift/attacks/schema.json").read_text()
)
errors = []
scenario_dir = pathlib.Path("mcpdrift/attacks")
recovery_dir = scenario_dir / "recovery"
scenario_files = [
    path
    for path in scenario_dir.rglob("*.json")
    if path.name != "schema.json" and recovery_dir not in path.parents
]

for path in scenario_files:
    try:
        jsonschema.validate(json.loads(path.read_text()), schema)
    except jsonschema.ValidationError as error:
        errors.append(f"{path}: {error.message}")

if errors:
    for error in errors:
        print(f"FAIL: {error}")
    sys.exit(1)

print(f"All scenarios valid ({len(scenario_files)} files)")