def count_occurrence(list_, comparison_key):
    result = []
    for item in list_:
        found_item = next((x for x in result if x["item"][f"{comparison_key}"] == item[f"{comparison_key}"]), None)

        if found_item is None:
            result.append({
                "item": item,
                "occurrence": 1
            })
            continue
        found_item["occurrence"] += 1

    return result
