import threading
from typing import Optional
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from aiokafka.structs import TopicPartition
from fastapi.params import Query
from pydantic.fields import Field
from starlette.websockets import WebSocket
import asyncio
import uvicorn
from pydantic import BaseModel
import time
from itertools import count
from fastapi.staticfiles import StaticFiles
from os import getenv
id_gen = count()

app = FastAPI()
KAFKA_HOST = getenv('KAFKA_HOST', "localhost")

class Message(BaseModel):
    text: str
    nick: str = "NoName"
    created_at: float = Field(default_factory=time.time)


async def consume(
    consumer: AIOKafkaConsumer,
    ws: WebSocket,
    stop_event: asyncio.Event,
):
    await consumer.start()
    await consumer.seek_to_end()
    assignment = consumer.assignment()
    offsets = await consumer.end_offsets(consumer.assignment())
    consumer.seek(list(assignment)[0], max(0, offsets[list(assignment)[0]] - 100))
    try:
        async for msg in consumer:
            await ws.send_text(Message.parse_raw(msg.value.decode("utf-8")).json())
    finally:
        stop_event.set()


async def produce(
    producer: AIOKafkaProducer,
    ws: WebSocket,
    stop_event: asyncio.Event,
    topic: str,
    nick: str,
):
    await producer.start()
    try:
        while True:
            data = await ws.receive_text()
            await producer.send(
                topic, Message(text=data, nick=nick).json().encode("utf-8")
            )
    finally:
        # Wait for all pending messages to be delivered or expire.
        stop_event.set()


@app.websocket("/chat")
async def chat(ws: WebSocket, topic: str, nick: Optional[str] = None):
    if not nick:
        nick = f"No Name {next(id_gen)}"

    await ws.accept()
    stop_event = asyncio.Event()

    consumer = AIOKafkaConsumer(topic, bootstrap_servers=KAFKA_HOST)
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_HOST)

    loop = asyncio.get_event_loop()

    loop.create_task(consume(consumer, ws, stop_event))
    loop.create_task(produce(producer, ws, stop_event, topic, nick))

    await stop_event.wait()
    consumer.unsubscribe()
    await consumer.stop()
    await producer.stop()


app.mount("/", StaticFiles(directory="static"), name="static")
uvicorn.run(app, host="0.0.0.0")