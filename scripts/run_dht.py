import argparse
import tesseract
from tesseract.utils import find_open_port


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=None, required=False)
    parser.add_argument('--initial_peers', type=str, default="[]", required=False)
    parser.add_argument('--lifetime_seconds', type=int, default=None, required=False)

    args = parser.parse_args()
    initial_peers = eval(args.initial_peers)
    print("Parsed initial peers:", initial_peers)

    network = tesseract.TesseractNetwork(*initial_peers, port=args.port or find_open_port())

    try:
        network.start()
        print(f"Running network node on port {network.port}")
        network.join(timeout=args.lifetime_seconds)
    finally:
        network.shutdown()