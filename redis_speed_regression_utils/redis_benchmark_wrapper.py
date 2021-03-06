import csv


def redis_benchmark_from_stdout_csv_to_json(stdout, tag, commit, start_time):
    results_dict = {"Tag": tag, "Commit": commit, "Commited-date": start_time, "Tests": {}}
    csv_data = list(csv.reader(stdout.decode('ascii').splitlines(), delimiter=","))
    print(csv_data)
    header = csv_data[0]
    for row in csv_data[1:]:
        test_name = row[0]
        results_dict["Tests"][test_name] = {}
        for pos, value in enumerate(row[1:]):
            results_dict["Tests"][test_name][header[pos + 1]] = value
    return results_dict
