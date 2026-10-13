"""Wait for a newly created Kafka partition to reach consumer metadata."""

import time

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition


def watermarks_when_ready(
    consumer: Consumer, partition: TopicPartition, timeout: float = 15
) -> tuple[int, int]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Kafka partition {partition.topic}[{partition.partition}] not ready"
            )
        try:
            # The create-topic acknowledgement can precede consumer metadata refresh.
            consumer.list_topics(topic=partition.topic, timeout=min(5, remaining))
            return consumer.get_watermark_offsets(partition, timeout=min(5, remaining))
        except KafkaException as error:
            if error.args[0].code() not in {
                KafkaError._UNKNOWN_PARTITION,
                KafkaError.UNKNOWN_TOPIC_OR_PART,
            }:
                raise
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
