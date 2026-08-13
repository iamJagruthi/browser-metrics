from difflib import SequenceMatcher


def normalize(text):
    if text is None:
        return ""

    return (
        str(text)
        .strip()
        .lower()
        .replace(":", "")
    )


def compare_kpis(source_kpis, target_kpis):

    results = []

    matched = 0

    target_lookup = {
        normalize(kpi.name): kpi
        for kpi in target_kpis
    }

    for source in source_kpis:

        key = normalize(source.name)

        target = target_lookup.get(key)

        if target is None:

            results.append({
                "kpi": source.name,
                "source": source.value,
                "target": None,
                "status": "Missing"
            })

            continue

        if normalize(source.value) == normalize(target.value):

            status = "Match"
            matched += 1

        else:

            status = "Changed"

        results.append({
            "kpi": source.name,
            "source": source.value,
            "target": target.value,
            "status": status
        })

    match_percentage = round(
        matched * 100 / max(len(results), 1),
        2
    )

    return {
        "results": results,
        "match_percentage": match_percentage
    }