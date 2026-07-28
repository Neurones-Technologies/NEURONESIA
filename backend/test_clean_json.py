import json
from modules.uc10_presales.scoring_pipeline import _clean_json

# 1. Trailing comma in object
bad1 = '{"a": 1, "b": 2,}'
assert json.loads(_clean_json(bad1)) == {"a": 1, "b": 2}
print("OK trailing comma in object")

# 2. Trailing comma in array
bad2 = '{"items": [1, 2, 3,]}'
assert json.loads(_clean_json(bad2)) == {"items": [1, 2, 3]}
print("OK trailing comma in array")

# 3. Nested trailing commas
bad3 = '{"a": [1, 2,], "b": {"x": 1,},}'
assert json.loads(_clean_json(bad3)) == {"a": [1, 2], "b": {"x": 1}}
print("OK nested trailing commas")

# 4. Markdown fence + trailing comma
bad4 = '```json\n{"k": [1,2,],}\n```'
assert json.loads(_clean_json(bad4)) == {"k": [1, 2]}
print("OK fence + trailing comma combined")

# 5. Valid JSON unchanged
good = '{"a": 1, "b": [1, 2]}'
assert json.loads(_clean_json(good)) == {"a": 1, "b": [1, 2]}
print("OK valid JSON preserved")

# 6. Comma inside string value not affected by trailing-comma regex
edge = '{"msg": "hello,"}'
assert json.loads(_clean_json(edge)) == {"msg": "hello,"}
print("OK comma inside string preserved")

# 7. Real newline inside string still escaped
multiline = '{"value": "line1\nline2"}'
assert json.loads(_clean_json(multiline)) == {"value": "line1\nline2"}
print("OK newline in string escaped")

print("\nAll tests passed.")
