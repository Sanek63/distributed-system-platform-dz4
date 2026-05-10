import os
import time
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

PORT = int(os.environ.get('PORT', 8000))
REDELIVERY_TIMEOUT_MS = int(os.environ.get('REDELIVERY_TIMEOUT_MS', 3000))

app = FastAPI(title="Message Broker")

topics = {}


class Message:
    def __init__(self, key: str, value: str):
        self.id = str(uuid.uuid4())
        self.key = key
        self.value = value
        self.timestamp = int(time.time() * 1000)
        self.offset = 0
        self.delivered_at = None
        self.acked = False


class Subscriber:
    def __init__(self, name: str):
        self.name = name
        self.processed_offset = -1
        self.pending_message = None


class Topic:
    def __init__(self, name: str):
        self.name = name
        self.messages = []
        self.subscribers = {}

    def add_message(self, key: str, value: str):
        msg = Message(key, value)
        msg.offset = len(self.messages)
        self.messages.append(msg)
        return msg

    def subscribe(self, name: str):
        if name not in self.subscribers:
            self.subscribers[name] = Subscriber(name)

    def get_next_message(self, subscriber_name: str):
        if subscriber_name not in self.subscribers:
            return None
        sub = self.subscribers[subscriber_name]
        
        # Повторная доставка при таймауте
        if sub.pending_message and not sub.pending_message.acked:
            elapsed = (time.time() * 1000) - sub.pending_message.delivered_at
            if elapsed >= REDELIVERY_TIMEOUT_MS:
                sub.pending_message.delivered_at = time.time() * 1000
                return sub.pending_message
            return None
        
        # Следующее сообщение
        next_offset = sub.processed_offset + 1
        if next_offset < len(self.messages):
            msg = self.messages[next_offset]
            msg.delivered_at = time.time() * 1000
            sub.pending_message = msg
            return msg
        return None

    def ack(self, subscriber_name: str, message_id: str) -> bool:
        if subscriber_name not in self.subscribers:
            return False
        sub = self.subscribers[subscriber_name]
        if sub.pending_message and sub.pending_message.id == message_id:
            sub.pending_message.acked = True
            sub.processed_offset = sub.pending_message.offset
            sub.pending_message = None
            return True
        return False


class CreateTopicRequest(BaseModel):
    name: str


class SubscribeRequest(BaseModel):
    topic: str
    subscriber: str


class PublishRequest(BaseModel):
    topic: str
    key: str
    value: str


class AckRequest(BaseModel):
    topic: str
    subscriber: str
    id: str


@app.post("/topics", status_code=201)
def create_topic(request: CreateTopicRequest):
    if request.name in topics:
        raise HTTPException(status_code=409, detail="Topic already exists")
    topics[request.name] = Topic(request.name)
    return {}


@app.post("/subscribe")
def subscribe(request: SubscribeRequest):
    if request.topic not in topics:
        raise HTTPException(status_code=404, detail="Topic not found")
    topics[request.topic].subscribe(request.subscriber)
    return {}


@app.post("/publish")
def publish(request: PublishRequest):
    if request.topic not in topics:
        raise HTTPException(status_code=404, detail="Topic not found")
    msg = topics[request.topic].add_message(request.key, request.value)
    return {"id": msg.id, "offset": msg.offset}


@app.get("/consume")
def consume(topic: str, subscriber: str):
    if topic not in topics:
        return {"status": "no_content"}
    msg = topics[topic].get_next_message(subscriber)
    if not msg:
        return {"status": "no_content"}
    return {
        "id": msg.id,
        "offset": msg.offset,
        "key": msg.key,
        "value": msg.value,
        "timestamp": msg.timestamp
    }


@app.post("/ack")
def ack(request: AckRequest):
    if request.topic not in topics:
        raise HTTPException(status_code=400, detail="Ack failed")
    if not topics[request.topic].ack(request.subscriber, request.id):
        raise HTTPException(status_code=400, detail="Ack failed")
    return {}


@app.get("/status")
def get_status():
    result = []
    for topic in topics.values():
        result.append({
            "name": topic.name,
            "messageCount": len(topic.messages),
            "subscribers": [{
                "name": sub.name,
                "processedOffset": sub.processed_offset,
                "pendingMessages": 1 if sub.pending_message and not sub.pending_message.acked else 0
            } for sub in topic.subscribers.values()]
        })
    return {"topics": result}


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)
