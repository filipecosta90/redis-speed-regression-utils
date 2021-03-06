import argparse
import logging
import shutil
import subprocess
import tempfile

import git
import redis
import semantic_version

# logging settings
logging.basicConfig(
    format="%(asctime)s %(levelname)-4s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="tbd",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--redis_mgt_host", type=str, default="localhost")
    parser.add_argument("--redis_mgt_port", type=int, default=6379)
    parser.add_argument("--redis_mgt_pass", type=str, default=None)
    parser.add_argument("--redis_repo", type=str, default=None)
    parser.add_argument("--trigger-version-tags", type=bool, default=True)
    parser.add_argument("--trigger-unstable-commits", type=bool, default=False)
    parser.add_argument("--dry-run", type=bool, default=False)
    args = parser.parse_args()
    redisMgtClient = None
    stream = "speed-regression-commits"
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
        logging.info(
            "Using the following redis repo to retrieve versions info {}. No need to fetch remote data.".format(
                redisDirPath))

    repo = git.Repo(redisDirPath)
    officialVersions = []
    Commits = []
    if args.trigger_version_tags is True:
        logging.info(
            "Using version tags to trigger speed tests.")
        for tag in repo.tags:

            if semantic_version.validate(tag.name) and "-" not in tag.name:
                # if semantic_version.Version(tag.name).major >= 6:
                officialVersions.append(tag)

        logging.info("Will trigger {} distinct version tests by version: {}.".format(len(officialVersions), ",".join(
            [x.name for x in officialVersions])))
    if args.trigger_unstable_commits is True:
        logging.info(
            "Using version tags to trigger speed tests.")
        for commit in repo.iter_commits():
            Commits.append(commit)
        logging.info(
            "Will trigger {} distinct unstable branch commit tests.".format(len(Commits) - len(officialVersions)))

    if args.dry_run is False:
        redisMgtClient = redis.StrictRedis(host=args.redis_mgt_host, port=args.redis_mgt_port,
                                           password=args.redis_mgt_pass,
                                           decode_responses=True)
        for tag in officialVersions:
            redisMgtClient.xadd(stream, {'commit': tag.commit.hexsha, 'committed-date': tag.commit.committed_date,
                                         'tag': tag.name,
                                         'benchmark-tool': "redis-benchmark",
                                         'setup': "oss-standalone"})

        for commit in Commits:
            redisMgtClient.xadd(stream, {'commit': commit.hexsha, 'committed-date': commit.committed_date, 'tag': "",
                                         'benchmark-tool': "redis-benchmark",
                                         'setup': "oss-standalone"})

    else:
        logging.info("Skipping actual work trigger ( dry-run )")

    if cleanUp is True:
        logging.info("Removing temporary redis dir {}.".format(redisDirPath))
        shutil.rmtree(redisDirPath)
