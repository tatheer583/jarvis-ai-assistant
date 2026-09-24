import multiprocessing
import sys
if __name__ == '__main__':
    multiprocessing.freeze_support()
    from Main import main
    if len(sys.argv) == 1:
        sys.argv.append('--engine')
    raise SystemExit(main())
