.PHONY: docker-build docker-shell docker-list docker-format docker-mount

DOCKER_IMAGE ?= cognitivefs:dev


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
