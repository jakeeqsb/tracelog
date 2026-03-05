#!/usr/bin/env bash

set -e

CPU=4
MEMORY=8
DISK=60
ARCH=aarch64  # Apple Silicon (M1~M4)

GREEN="\033[32m"
CYAN="\033[36m"
RESET="\033[0m"

start_colima() {
    echo -e "${CYAN}▶ Starting Colima (M4 optimized)...${RESET}"
    colima start \
        --cpu $CPU \
        --memory $MEMORY \
        --disk $DISK \
        --arch $ARCH \
        --vm-type vz \
        --vz-rosetta \
        --runtime docker \
        --mount-type virtiofs \
        --network-address \
        --dns 1.1.1.1
    echo -e "${GREEN}✔ Colima started${RESET}"
}

stop_colima() {
    echo -e "${CYAN}▶ Stopping Colima...${RESET}"
    colima stop
    echo -e "${GREEN}✔ Colima stopped${RESET}"
}

restart_colima() {
    stop_colima
    start_colima
}

status() {
    echo -e "${CYAN}▶ Colima Status${RESET}"
    colima status
}

docker_up() {
    echo -e "${CYAN}▶ Starting Docker Compose...${RESET}"
    docker-compose up -d --build
    echo -e "${GREEN}✔ Docker services running${RESET}"
}

docker_down() {
    echo -e "${CYAN}▶ Stopping containers...${RESET}"
    docker-compose down
    echo -e "${GREEN}✔ Docker services stopped${RESET}"
}

clean_all() {
    echo -e "${CYAN}▶ Removing Colima VM & Docker junk...${RESET}"
    colima delete --force
    docker system prune -a --volumes --force
    echo -e "${GREEN}✔ Clean complete${RESET}"
}

case "$1" in
    start) start_colima ;;
    stop) stop_colima ;;
    restart) restart_colima ;;
    status) status ;;
    up) start_colima; docker_up ;;
    down) docker_down ;;
    clean) clean_all ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|up|down|clean}"
        exit 1
        ;;
esac