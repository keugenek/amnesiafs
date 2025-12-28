.PHONY: docker-build docker-shell docker-list docker-format docker-mount
.PHONY: eval-build eval-run eval-shell eval-clean

DOCKER_IMAGE ?= cognitivefs:dev


# ============== Development Targets ==============

docker-build:
	docker build -t $(DOCKER_IMAGE) .


docker-shell:
	docker compose run --rm --entrypoint bash cognitivefs


docker-list:
	docker compose run --rm cognitivefs list


docker-format:
	docker compose run --rm cognitivefs format $(DEVICE) --force


docker-mount:
	docker compose run --rm cognitivefs mount $(DEVICE) $(MOUNTPOINT) --debug


# ============== RAGAS Evaluation Targets ==============

eval-build:
	docker compose -f docker-compose.eval.yml build


eval-run:
	./scripts/run-eval.sh


eval-shell:
	./scripts/eval-shell.sh


eval-clean:
	docker compose -f docker-compose.eval.yml down -v
	rm -rf eval-results/*.json
