import os
import json
import time
import uuid
import threading
import requests
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get('PORT', 8001))
BROKER_URL = os.environ.get('BROKER_URL', 'http://broker:8000')

COMMAND_TOPICS = {
    'warehouse': 'warehouse-commands',
    'payment': 'payment-commands',
    'delivery': 'delivery-commands'
}
RESULT_TOPICS = {
    'warehouse': 'warehouse-results',
    'payment': 'payment-results',
    'delivery': 'delivery-results'
}

app = FastAPI(title="Saga Orchestrator")

orders = {}
lock = threading.Lock()


def init_topics():
    for topic in list(COMMAND_TOPICS.values()) + list(RESULT_TOPICS.values()):
        try:
            requests.post(f'{BROKER_URL}/topics', json={'name': topic}, timeout=2)
        except:
            pass
    for topic in RESULT_TOPICS.values():
        try:
            requests.post(f'{BROKER_URL}/subscribe', json={'topic': topic, 'subscriber': 'orchestrator'}, timeout=2)
        except:
            pass


def publish(topic: str, key: str, value: str):
    try:
        requests.post(f'{BROKER_URL}/publish', json={'topic': topic, 'key': key, 'value': value}, timeout=2)
    except:
        pass


def get_order_safe(order_id):
    with lock:
        return orders.get(order_id)


def update_order(order_id, updates):
    with lock:
        if order_id in orders:
            orders[order_id].update(updates)


def handle_result(result):
    order_id = result.get('orderId')
    action = result.get('action')
    status = result.get('status')
    
    logger.info(f"Result: {order_id} {action} {status}")
    
    order = get_order_safe(order_id)
    if not order:
        logger.warning(f"Order {order_id} not found")
        return

    if order.get('compensating'):
        if status == 'success':
            process_compensation(order)
        return

    if action == 'reserve' and status == 'success':
        update_order(order_id, {'completed_steps': order['completed_steps'] + ['warehouse'], 'status': 'payment-processing'})
        publish(COMMAND_TOPICS['payment'], order_id, json.dumps({
            'orderId': order_id,
            'action': 'charge',
            'amount': order['payment_amount']
        }))
    elif action == 'reserve' and status == 'failure':
        update_order(order_id, {'status': 'cancelled'})
    elif action == 'charge' and status == 'success':
        update_order(order_id, {'completed_steps': order['completed_steps'] + ['payment'], 'status': 'delivery-scheduling'})
        publish(COMMAND_TOPICS['delivery'], order_id, json.dumps({
            'orderId': order_id,
            'action': 'schedule',
            'address': order['delivery_address'],
            'items': order['items']
        }))
    elif action == 'charge' and status == 'failure':
        # T2 failed → compensate T1 (warehouse)
        update_order(order_id, {'compensating': True, 'status': 'compensating', 'compensation_index': 0})
        process_compensation(order)
    elif action == 'schedule' and status == 'success':
        update_order(order_id, {'completed_steps': order['completed_steps'] + ['delivery'], 'status': 'completed'})
    elif action == 'schedule' and status == 'failure':
        # T3 failed → compensate T2 (payment), then T1 (warehouse)
        update_order(order_id, {'compensating': True, 'status': 'compensating', 'compensation_index': 1})
        process_compensation(order)


def process_compensation(order):
    order_id = order['order_id']
    idx = order.get('compensation_index', 0)
    
    if idx < 0:
        update_order(order_id, {'status': 'cancelled', 'compensating': False})
        return
    
    if idx == 0:  # C1: Cancel reserve
        update_order(order_id, {'compensated_steps': order['compensated_steps'] + ['warehouse'], 'compensation_index': -1})
        publish(COMMAND_TOPICS['warehouse'], order_id, json.dumps({
            'orderId': order_id,
            'action': 'cancel-reserve'
        }))
    elif idx == 1:  # C2: Refund → then C1
        update_order(order_id, {'compensated_steps': order['compensated_steps'] + ['payment'], 'compensation_index': 0})
        publish(COMMAND_TOPICS['payment'], order_id, json.dumps({
            'orderId': order_id,
            'action': 'refund'
        }))
    elif idx == 2:  # C3: Cancel delivery → then C2 → C1
        update_order(order_id, {'compensated_steps': order['compensated_steps'] + ['delivery'], 'compensation_index': 1})
        publish(COMMAND_TOPICS['delivery'], order_id, json.dumps({
            'orderId': order_id,
            'action': 'cancel-delivery'
        }))


def poll_results():
    logger.info("Starting poll...")
    while True:
        for topic in RESULT_TOPICS.values():
            try:
                resp = requests.get(f'{BROKER_URL}/consume?topic={topic}&subscriber=orchestrator', timeout=1)
                if resp.status_code == 200:
                    data = resp.json()
                    if 'id' in data:
                        logger.info(f"Got message from {topic}: {data}")
                        result = json.loads(data['value'])
                        handle_result(result)
                        requests.post(f'{BROKER_URL}/ack', json={
                            'topic': topic,
                            'subscriber': 'orchestrator',
                            'id': data['id']
                        }, timeout=1)
            except Exception as e:
                logger.warning(f"Poll error: {e}")
                pass
        time.sleep(0.1)


class OrderRequest(BaseModel):
    items: list
    paymentAmount: int
    deliveryAddress: str


@app.on_event("startup")
async def startup():
    logger.info("Orchestrator starting...")
    init_topics()
    t = threading.Thread(target=poll_results, daemon=True)
    t.start()
    logger.info("Poll thread started")


@app.post("/order")
def create_order(request: OrderRequest):
    order_id = str(uuid.uuid4())[:8]
    order = {
        'order_id': order_id,
        'items': request.items,
        'payment_amount': request.paymentAmount,
        'delivery_address': request.deliveryAddress,
        'status': 'warehouse-reserving',
        'completed_steps': [],
        'compensated_steps': [],
        'compensating': False,
        'compensation_index': 0
    }
    with lock:
        orders[order_id] = order
    
    publish(COMMAND_TOPICS['warehouse'], order_id, json.dumps({
        'orderId': order_id,
        'action': 'reserve',
        'items': request.items
    }))
    
    return {'orderId': order_id, 'status': order['status']}


@app.get("/orders")
def get_orders():
    with lock:
        return {'orders': [{'orderId': o['order_id'], 'status': o['status']} for o in orders.values()]}


@app.get("/order/{order_id}")
def get_order(order_id: str):
    with lock:
        order = orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        'orderId': order['order_id'],
        'status': order['status'],
        'completedSteps': order['completed_steps'],
        'compensatedSteps': order['compensated_steps']
    }


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)
