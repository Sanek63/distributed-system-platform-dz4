import os
import json
import time
import threading
import requests
import logging
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get('PORT', 8004))
BROKER_URL = os.environ.get('BROKER_URL', 'http://broker:8000')
FAIL_ACTION = os.environ.get('FAIL_ACTION')

deliveries = {}
processed_ids = set()
lock = threading.Lock()

TOPIC = 'delivery-commands'
RESULT_TOPIC = 'delivery-results'
SUBSCRIBER = 'delivery'

app = FastAPI(title="Delivery Service")


def publish_result(order_id, action, status, message):
    try:
        requests.post(f'{BROKER_URL}/publish', json={
            'topic': RESULT_TOPIC,
            'key': order_id,
            'value': json.dumps({
                'orderId': order_id,
                'action': action,
                'status': status,
                'message': message
            })
        }, timeout=2)
    except Exception as e:
        logger.error(f"Publish failed: {e}")


def handle_command(msg):
    data = json.loads(msg['value'])
    order_id = data.get('orderId')
    action = data.get('action')
    message_id = msg['id']

    logger.info(f"Command: {order_id} {action}")

    with lock:
        if message_id in processed_ids:
            return
        processed_ids.add(message_id)

    if action == 'schedule':
        if FAIL_ACTION == 'schedule':
            publish_result(order_id, 'schedule', 'failure', 'Failed')
            return
        deliveries[order_id] = {
            'address': data.get('address', ''),
            'items': data.get('items', [])
        }
        publish_result(order_id, 'schedule', 'success', 'Scheduled')
    elif action == 'cancel-delivery':
        if order_id in deliveries:
            del deliveries[order_id]
        publish_result(order_id, 'cancel-delivery', 'success', 'Cancelled')


def poll_commands():
    for _ in range(30):
        try:
            r = requests.post(f'{BROKER_URL}/subscribe', json={'topic': TOPIC, 'subscriber': SUBSCRIBER}, timeout=2)
            if r.status_code == 200:
                break
        except:
            pass
        time.sleep(1)

    while True:
        try:
            r = requests.get(f'{BROKER_URL}/consume?topic={TOPIC}&subscriber={SUBSCRIBER}', timeout=1)
            if r.status_code == 200:
                data = r.json()
                if 'id' in data:
                    handle_command(data)
                    requests.post(f'{BROKER_URL}/ack', json={
                        'topic': TOPIC,
                        'subscriber': SUBSCRIBER,
                        'id': data['id']
                    }, timeout=1)
        except:
            pass
        time.sleep(0.5)


@app.on_event("startup")
async def startup():
    logger.info("Delivery starting...")
    t = threading.Thread(target=poll_commands, daemon=True)
    t.start()
    logger.info("Poll thread started")


@app.get("/status")
def get_status():
    with lock:
        return {
            'deliveries': dict(deliveries),
            'processedMessages': len(processed_ids)
        }


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)
