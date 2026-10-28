"""Fixture: the Spark privacy boundary."""


def leaks(store, session):
    return build_spark_context(store, session)  # expect: sym-spark-privacy


def leaks_by_keyword(self_store):
    return spark_history(source=self_store)  # expect: sym-spark-privacy


def leaks_private_record(record_text):
    return render_prompt(record_text, Provenance(dataset="private", license="none", spark_safe=False))  # expect: sym-spark-privacy


def safe(store, session):
    return build_spark_context(store.spark_view(), session)


def not_spark(store):
    return count_records(store)


def safe_prompt(record_text):
    return render_prompt(record_text, Provenance(dataset="public", license="MIT", spark_safe=True))
