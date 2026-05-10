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

PORT = int(os.environ.get('PORT', 8002))
BROKER_URL = os.environ.get('BROKER_URL', 'http://broker:8000')
INITIAL_INVENTORY = os.environ.get('INITIAL_INVENTORY', 'item1:100,item2:50')

inventory = {}
for item in INITIAL_INVENTORY.split(','):
    if ':' in item:
        name, qty = item.split(':')
        inventory[name.strip()] = int(qty.strip())

reservations = {}
processed_ids = set()
lock = threading.Lock()

TOPIC = 'warehouse-commands'
RESULT_TOPIC = 'warehouse-results'
SUBSCRIBER = 'warehouse'

app = FastAPI(title="Warehouse Service")


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
    global inventory
    data = json.loads(msg['value'])
    order_id = data.get('orderId')
    action = data.get('action')
    message_id = msg['id']

    logger.info(f"Command: {order_id} {action}")

    with lock:
        if message_id in processed_ids:
            return
        processed_ids.add(message_id)

    if action == 'reserve':
        items = data.get('items', [])
        can_reserve = all(inventory.get(i.get('item'), 0) >= i.get('quantity', 0) for i in items)
        if can_reserve:
            for i in items:
                inventory[i['item']] -= i['quantity']
            reservations[order_id] = items
            publish_result(order_id, 'reserve', 'success', 'Reserved')
        else:
            publish_result(order_id, 'reserve', 'failure', 'Insufficient inventory')
    elif action == 'cancel-reserve':
        if order_id in reservations:
            for i in reservations[order_id]:
                inventory[i['item']] += i['quantity']
            del reservations[order_id]
        publish_result(order_id, 'cancel-reserve', 'success', 'Cancelled')


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
    threading.Thread(target=poll_commands, daemon=True).start()


@app.get("/status")
def get_status():
    with lock:
        return {
            'inventory': dict(inventory),
            'reservations': dict(reservations),
            'processedMessages': len(processed_ids)
        }


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)
