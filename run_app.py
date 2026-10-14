"""Ponto de entrada usado pelo PyInstaller e para execução direta: python run_app.py"""
import multiprocessing
import sys

from prancha.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
