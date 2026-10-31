"""Evidence entry shares authentication, local configuration and startup options."""
from run_web import main

if __name__ == '__main__':
    main(default_port=8766, evidence=True)
