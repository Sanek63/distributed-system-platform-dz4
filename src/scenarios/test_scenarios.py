import requests
import time
import sys

ORCH = 'http://localhost:8001'
WH = 'http://localhost:8002'
PAY = 'http://localhost:8003'
DEL = 'http://localhost:8004'


def wait_order(order_id, timeout=30):
    """Ждём завершения заказа (completed или cancelled)"""
    for _ in range(timeout * 2):
        r = requests.get(f'{ORCH}/order/{order_id}').json()
        if r['status'] in ('completed', 'cancelled'):
            return r
        time.sleep(0.5)
    return None


def scenario_1():
    """Сценарий 1: Успешная обработка заказа"""
    print("\nСценарий 1: Успешный заказ")

    o = requests.post(f'{ORCH}/order', json={
        'items': [{'item': 'item1', 'quantity': 2}],
        'paymentAmount': 500,
        'deliveryAddress': 'Test St'
    }).json()
    print(f"  Заказ: {o['orderId']}")

    r = wait_order(o['orderId'])
    print(f"  Статус: {r['status']}")

    wh = requests.get(f'{WH}/status').json()
    pay = requests.get(f'{PAY}/status').json()
    dl = requests.get(f'{DEL}/status').json()

    print(f"  Склад: inventory={wh['inventory']}, reservations={len(wh['reservations'])}")
    print(f"  Оплата: balance={pay['balance']}, charges={len(pay['charges'])}")
    print(f"  Доставка: deliveries={len(dl['deliveries'])}")

    if r['status'] == 'completed':
        print("  Успешно")
    else:
        print("  Ошибка")


def scenario_2():
    """Сценарий 2: Недостаточный баланс"""
    print("\nСценарий 2: Недостаточный баланс")

    pay = requests.get(f'{PAY}/status').json()
    amount = pay['balance'] + 450
    print(f"  Баланс: {pay['balance']}, списание: {amount}")

    o = requests.post(f'{ORCH}/order', json={
        'items': [{'item': 'item1', 'quantity': 1}],
        'paymentAmount': amount,
        'deliveryAddress': 'Test'
    }).json()
    print(f"  Заказ: {o['orderId']}")

    r = wait_order(o['orderId'])
    print(f"  Статус: {r['status']}")

    wh = requests.get(f'{WH}/status').json()
    print(f"  Склад: reservations={len(wh['reservations'])}")

    if r['status'] == 'cancelled' and o['orderId'] not in wh.get('reservations', {}):
        print("  Компенсация выполнена")
    else:
        print("  Ошибка")


def scenario_3():
    """Сценарий 3: Отказ доставки"""
    print("\nСценарий 3: Отказ доставки")

    o = requests.post(f'{ORCH}/order', json={
        'items': [{'item': 'item1', 'quantity': 1}],
        'paymentAmount': 100,
        'deliveryAddress': 'Test'
    }).json()
    print(f"  Заказ: {o['orderId']}")

    r = wait_order(o['orderId'])
    print(f"  Статус: {r['status']}, компенсировано: {r.get('compensatedSteps', [])}")

    wh = requests.get(f'{WH}/status').json()
    pay = requests.get(f'{PAY}/status').json()

    print(f"  Склад: inventory={wh['inventory']}")
    print(f"  Оплата: balance={pay['balance']}")

    if r['status'] == 'cancelled':
        print("  Компенсация выполнена")
    else:
        print("  Ошибка")


def scenario_4():
    """Сценарий 4: Повторная доставка"""
    print("\nСценарий 4: Redelivery")
    print("  Требует ручного тестирования с перезапуском сервиса")
    print("  Брокер повторно доставит сообщение при отсутствии ack")


def scenario_5():
    """Сценарий 5: Параллельные заказы"""
    print("\nСценарий 5: Параллельные заказы")

    num_orders = 10
    payment_amount = 500
    items = [{'item': 'item1', 'quantity': 5}]
    initial_inventory = 100
    initial_balance = 10000

    print(f"  Отправляем {num_orders} заказов параллельно...")
    print(f"  Каждый заказ: paymentAmount={payment_amount}, items={items}")

    order_ids = []
    for i in range(num_orders):
        o = requests.post(f'{ORCH}/order', json={
            'items': items,
            'paymentAmount': payment_amount,
            'deliveryAddress': f'Test St {i}'
        }).json()
        order_ids.append(o['orderId'])

    print(f"  Создано заказов: {len(order_ids)}")

    completed = 0
    cancelled = 0
    for oid in order_ids:
        r = wait_order(oid)
        if r and r['status'] == 'completed':
            completed += 1
        elif r and r['status'] == 'cancelled':
            cancelled += 1

    print(f"\n  Результаты: completed={completed}, cancelled={cancelled}")

    wh = requests.get(f'{WH}/status').json()
    pay = requests.get(f'{PAY}/status').json()

    current_inventory = wh['inventory'].get('item1', 0)
    reservations_count = sum(sum(item['quantity'] for item in res) for res in wh['reservations'].values())
    total_inventory = current_inventory + reservations_count

    charges_total = sum(pay['charges'].values())
    total_balance = pay['balance'] + charges_total

    print(f"\n  Финальное состояние:")
    print(f"    Склад: inventory={current_inventory}, reservations={reservations_count}, total={total_inventory} (начальный={initial_inventory})")
    print(f"    Оплата: balance={pay['balance']}, charges={charges_total}, total={total_balance} (начальный={initial_balance})")

    inventory_ok = total_inventory == initial_inventory
    balance_ok = total_balance == initial_balance

    print(f"\n  Проверка согласованности:")
    print(f"    Склад: {'OK' if inventory_ok else 'FAIL'}")
    print(f"    Оплата: {'OK' if balance_ok else 'FAIL'}")

    if completed == num_orders and inventory_ok and balance_ok:
        print("\n  Все заказы успешно завершены, состояние согласовано")
    else:
        print(f"\n  Завершено {completed} из {num_orders}, согласованность: склад={'OK' if inventory_ok else 'FAIL'}, оплата={'OK' if balance_ok else 'FAIL'}")


def main():
    if len(sys.argv) > 1:
        num = sys.argv[1]
        if num == '1':
            scenario_1()
        elif num == '2':
            scenario_2()
        elif num == '3':
            scenario_3()
        elif num == '4':
            scenario_4()
        elif num == '5':
            scenario_5()
        else:
            print(f"Неизвестный сценарий: {num}")
    else:
        print("\nЗапуск всех сценариев\n")
        scenario_1()
        print()
        scenario_2()
        print()
        scenario_3()
        print()
        scenario_4()
        print()
        scenario_5()
        print("\nТесты завершены\n")


if __name__ == '__main__':
    main()
