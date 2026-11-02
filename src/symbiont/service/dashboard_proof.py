"""The measured results the dashboard's proof band shows; each carries its tag and its limits."""

PROOF = [
    {
        "id": "wrong-notes",
        "tag": "measured",
        "big": "0",
        "unit": "wrong notes in 501 shown",
        "claim": "None of the 501 notes it showed were wrong.",
        "source": "Agree rule, 251 repeats in 89 unseen repos. Each dot is one note shown.",
        "footer": ["0 wrong notes", " in 501 shown"],
        "chart": {"shown": 501, "wrong": 0},
    },
    {
        "id": "nightly-training",
        "tag": "measured",
        "big": "61%",
        "unit": "vs 0%",
        "claim": "of repeats caught after nightly training, against none without it.",
        "source": "Code-fix study, 924 items, 97.8% precision.",
        "footer": ["61%", " of repeats caught vs 0%"],
        "chart": {"withTraining": 61, "without": 0},
    },
    {
        "id": "spark-rule",
        "tag": "measured",
        "big": "+0.16",
        "unit": "[0.11, 0.22]",
        "claim": "A rule Spark wrote from its own failures made it better, and held on new cases.",
        "source": "Replicated on 240 fresh cases.",
        "footer": ["+0.16", " [0.11, 0.22], replicated on 240 fresh cases"],
        "chart": {"estimate": 0.16, "low": 0.11, "high": 0.22},
    },
]
