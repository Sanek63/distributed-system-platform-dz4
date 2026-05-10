.PHONY: help build up down logs scenario-1 scenario-2 scenario-3 scenario-4 scenario-5 demo clean

GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m

help:
	@echo "$(BLUE)=== Saga Pattern Demo ===$(NC)"
	@echo ""
	@echo "$(GREEN)build$(NC)       — собрать Docker образы"
	@echo "$(GREEN)up$(NC)          — запустить сервисы"
	@echo "$(GREEN)down$(NC)         — остановить сервисы"
	@echo "$(GREEN)logs$(NC)         — логи всех сервисов"
	@echo "$(GREEN)scenario-1$(NC)   — успешный заказ"
	@echo "$(GREEN)scenario-2$(NC)   — недостаточный баланс"
	@echo "$(GREEN)scenario-3$(NC)   — отказ доставки"
	@echo "$(GREEN)scenario-4$(NC)   — redelivery"
	@echo "$(GREEN)scenario-5$(NC)   — параллельные заказы"
	@echo "$(GREEN)demo$(NC)         — все сценарии"
	@echo "$(GREEN)clean$(NC)        — очистка"

build:
	docker-compose build

up:
	@echo "$(GREEN)Запуск сервисов...$(NC)"
	docker-compose up -d
	@echo "$(YELLOW)Ожидание (15 сек)...$(NC)"
	sleep 15
	@echo "$(GREEN)Готово!$(NC)"
	@echo "  Broker:       http://localhost:8000/status"
	@echo "  Orchestrator: http://localhost:8001/orders"
	@echo "  Warehouse:    http://localhost:8002/status"
	@echo "  Payment:      http://localhost:8003/status"
	@echo "  Delivery:     http://localhost:8004/status"

down:
	docker-compose down

logs:
	docker-compose logs -f

scenario-1:
	@echo "$(BLUE)=== Сценарий 1: Успешный заказ ===$(NC)"
	cd src && python3 scenarios/test_scenarios.py 1

scenario-2:
	@echo "$(BLUE)=== Сценарий 2: Недостаточный баланс ===$(NC)"
	cd src && python3 scenarios/test_scenarios.py 2

scenario-3:
	@echo "$(BLUE)=== Сценарий 3: Отказ доставки ===$(NC)"
	@echo "$(YELLOW)Запуск delivery-fail...$(NC)"
	docker-compose --profile fail up -d delivery-fail
	sleep 5
	cd src && python3 scenarios/test_scenarios.py 3
	@echo "$(YELLOW)Остановка delivery-fail...$(NC)"
	docker-compose --profile fail stop delivery-fail

scenario-4:
	@echo "$(BLUE)=== Сценарий 4: Повторная доставка ===$(NC)"
	cd src && python3 scenarios/test_scenarios.py 4

scenario-5:
	@echo "$(BLUE)=== Сценарий 5: Параллельные заказы ===$(NC)"
	cd src && python3 scenarios/test_scenarios.py 5

demo:
	@echo "$(BLUE)=== Демонстрация всех сценариев ===$(NC)"
	@echo ""
	@make scenario-1
	@echo ""
	@make scenario-2
	@echo ""
	@make scenario-3
	@echo ""
	@make scenario-4
	@echo ""
	@make scenario-5

clean:
	docker-compose down --rmi all -v
