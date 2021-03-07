import argparse
import logging
import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import closing

import redis

# logging settings
from redis_speed_regression_utils.redis_benchmark_wrapper import redis_benchmark_from_stdout_csv_to_json
from redis_speed_regression_utils.redis_standalone import spinUpLocalRedis, isProcessAlive

logging.basicConfig(
    format="%(asctime)s %(levelname)-4s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)


def findFreePort():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(
        description="tbd",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--redis_mgt_host", type=str, default="localhost")
    parser.add_argument("--redis_mgt_port", type=int, default=6379)
    parser.add_argument("--redis_mgt_pass", type=str, default=None)
    parser.add_argument("--redis_repo", type=str, default=None)
    parser.add_argument("--taskset-redis", type=str, default=None)
    parser.add_argument("--taskset-make", type=str, default=None)
    parser.add_argument("--taskset-redis-benchmark", type=str, default=None)
    args = parser.parse_args()

    redisDirPath = args.redis_repo
    cleanUp = False
    if redisDirPath is None:
        cleanUp = True
        redisDirPath = tempfile.mkdtemp()
        logging.info("Retrieving redis repo from remote into {}.".format(redisDirPath))
        cmd = "git clone https://github.com/redis/redis {}\n".format(redisDirPath)
        process = subprocess.Popen('/bin/bash', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out, err = process.communicate(cmd.encode())
    else:
        redisDirPath = os.path.abspath(redisDirPath)
        logging.info(
            "Using the following redis repo to retrieve versions info {}. No need to fetch remote data.".format(
                redisDirPath))

    redisMgtClient = None
    stream = "speed-regression-commits"
    consumerGroup = "speed-regression-workers"
    logging.info("Using stream named {} to track regression test requests.".format(stream))
    redisMgtClient = redis.StrictRedis(host=args.redis_mgt_host, port=args.redis_mgt_port, password=args.redis_mgt_pass,
                                       decode_responses=True)
    try:
        redisMgtClient.xgroup_create(stream, consumerGroup, mkstream=True)
        logging.info("Created consumer group named {} to distribute work.".format(consumerGroup))
    except redis.exceptions.ResponseError as e:
        logging.info("Consumer group named {} already existed.".format(consumerGroup))
    while True:
        logging.info("Entering blocking read waiting for work.")
        newTestInfo = redisMgtClient.xreadgroup(consumerGroup, "redis-speed-regression-proc#", {stream: '>'}, count=1,
                                                block=0)
        streamId, testDetails = newTestInfo[0][1][0]
        logging.info("Received work {}.".format(testDetails))
        commit = None
        commited_date = ""
        tag = ""
        benchmark_config = {}
        if 'commit' in testDetails:
            commit = testDetails['commit']
            tag = testDetails['tag']
            commited_date = testDetails['committed-date']
            logging.info("Received commit hash specifier {}.".format(commit))
        else:
            logging.error("Missing commit information within received message.")
            continue
        port = findFreePort()

        cmd = "cd {}\n".format(redisDirPath)
        cmd += "git checkout {}\n".format(commit)
        taskset_make = ""
        if args.taskset_make:
            taskset_make = "taskset -c {} ".format(args.taskset_make)
        cmd += "{}make distclean\n".format(taskset_make)
        cmd += "{}make redis-server -j 3\n".format(taskset_make)
        process = subprocess.Popen('/bin/bash', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out, err = process.communicate(cmd.encode())
        if process.returncode != 0:
            logging.error("Unable to build redis for commit {}.".format(commit))
            continue

        # ... do stuff with dirpath

        # setup Redis
        redis_server_path = "{}/src/redis-server".format(redisDirPath)
        redis_process = spinUpLocalRedis(
            port,
            redis_server_path,
            args.taskset_redis
        )

        if isProcessAlive(redis_process) is False:
            logging.error("Unable to start redis for commit {}.".format(commit))
            continue
        executable_path = "redis-benchmark"
        command = []
        if args.taskset_redis_benchmark is not None:
            command.extend(["taskset", "-c", args.taskset_redis_benchmark])
        command.extend([executable_path])
        command.extend(["-p", "{}".format(port)])
        command.extend(["-d", "256", "--threads", "2", "--csv", "-e", "-n", "5000000", "-t", "set,get,hset,sadd,zadd"])
        logging.info(
            "Running redis-benchmark with the following args: {}".format(
                " ".join(command)
            )
        )
        benchmark_client_process = subprocess.Popen(args=command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        (stdout, sterr) = benchmark_client_process.communicate(cmd.encode())
        logging.info("Extracting the benchmark results")
        results_dict = redis_benchmark_from_stdout_csv_to_json(stdout, tag, commit, commited_date)
        for testname, results in results_dict["Tests"].items():
            rps = results["rps"]
            p50_latency_ms = results["p50_latency_ms"]
            with open('{}.csv'.format(testname), mode='a') as file_:
                file_.write("{},{},{},{},{}\n".format(tag, commit, commited_date, rps, p50_latency_ms))
        redis_process.kill()
        redisMgtClient.xack(stream, consumerGroup, streamId)
    if cleanUp is True:
        logging.info("Removing temporary redis dir {}.".format(redisDirPath))
        shutil.rmtree(redisDirPath)
