from browser import launch_browser
from metrics import build_metrics
from network import capture_network
from report import generate_report

def main():
    page = launch_browser()

    metrics = collect_metrics(page)
    network = capture_network(page)

    generate_report(metrics, network, console)

if __name__ == "__main__":
    main()