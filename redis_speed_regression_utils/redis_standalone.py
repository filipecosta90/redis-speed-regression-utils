import logging
import subprocess
import tempfile
import time

import redis


def waitForConn(conn, retries=20, command="PING", shouldBe=True):
    """Wait until a given Redis connection is ready"""
    result = False
    err1 = ""
    while retries > 0 and result is False:
        try:
            if conn.execute_command(command) == shouldBe:
                result = True
        except redis.exceptions.BusyLoadingError:
            time.sleep(0.1)  # give extra 100msec in case of RDB loading
        except redis.ConnectionError as err:
            err1 = str(err)
        except redis.ResponseError as err:
            err1 = str(err)
            if not err1.startswith("DENIED"):
                raise
        time.sleep(0.1)
        retries -= 1
        logging.debug("Waiting for Redis")
    return result


def spinUpLocalRedis(
        port,
        redisProcess="redis-server",
        taskset=None
):
    # copy the rdb to DB machine
    dataset = None
    temporary_dir = tempfile.mkdtemp()
    logging.info(
        "Using local temporary dir to spin up Redis Instance. Path: {}".format(
            temporary_dir
        )
    )
    command = []
    if taskset is not None:
        command.extend(["taskset", "-c", taskset])
    # start redis-server
    command.extend([
        redisProcess,
        "--save",
        '""',
        "--port",
        "{}".format(port),
        "--dir",
        temporary_dir,
    ])
    logging.info(
        "Running local redis-server with the following args: {}".format(
            " ".join(command)
        )
    )
    redis_process = subprocess.Popen(command)
    result = waitForConn(redis.StrictRedis(port=port))
    if result is True:
        logging.info("Redis available at port {}".format(port))
    return redis_process


def isProcessAlive(process):
    if not process:
        return False
    # Check if child process has terminated. Set and return returncode
    # attribute
    if process.poll() is None:
        return True
    return False
