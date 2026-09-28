import sys

from harvester.common import WorkerApp

if __name__ == "__main__":
    WorkerApp(sys.argv[1:]).run()
