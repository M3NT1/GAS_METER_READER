import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


def main():
    parser = argparse.ArgumentParser(description='Gázóra fotónapló – helyi feldolgozó')
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-watch', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path.cwd() / '.env', override=False)
    from .web import create_app
    app = create_app(Path(args.data_dir), watch=not args.no_watch)
    print(f'Gázóra fotónapló: http://127.0.0.1:{args.port}')
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
