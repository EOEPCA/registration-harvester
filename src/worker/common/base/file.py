import os
import tarfile


def untar_file(tar_file, remove_tar=True, create_folder=False, base_folder=None):
    """
    Untars a file and lists failed files

    Arguments:
        tar_file: tar file to untar
        remove_tar: Whether tar file is being removed or not (default: True)

    Returns:
        path to folder of untared file
    """
    if not os.path.exists(tar_file):
        raise Exception("File does not exist: %s" % tar_file)

    tar_ref = tarfile.open(tar_file, "r:")
    if not base_folder:
        base_folder = os.path.dirname(tar_file)
    if create_folder:
        scene_name = os.path.splitext(os.path.basename(tar_file))[0]
        extract_dir = os.path.join(base_folder, scene_name)
    else:
        extract_dir = base_folder

    failed_files = dict()
    failed_logs = ""

    for name in tar_ref.getnames():
        try:
            tar_ref.extract(name, extract_dir)
        except Exception as e:
            if "File exists" in str(e):
                continue
            failed_files[name] = str(e)
            failed_logs += name + ": " + str(e) + "\n"

    tar_ref.close()

    if len(failed_files) > 0:
        raise Exception("Exceptions during untaring: %s\n\n%s" % (tar_file, failed_logs))
    else:
        tar_removed = False
        if remove_tar:
            try:
                os.remove(tar_file)
                tar_removed = True
                print("Tar-File successfully removed: %s" % tar_file)
            except Exception as e:
                print(e)
                print("Tar-File could not be removed: %s" % tar_file)
        return (extract_dir, tar_removed)


def check_file_size(expected_file_size, file_path):
    if os.path.isfile(file_path):
        actual_file_size = os.path.getsize(file_path)
        if expected_file_size == actual_file_size:
            return True
        else:
            print(f"Different file sizes - {expected_file_size} expected - {actual_file_size} found")
            return False
    else:
        raise Exception("File not found: {file_path}")


def get_file_size(file_path):
    if not os.path.exists(file_path):
        raise Exception("File %s does not exist!" % file_path)
    stat = os.stat(file_path)
    return stat.st_size


def get_folder_size(folder_path):
    if not os.path.exists(folder_path):
        raise Exception("Folder %s does not exist!" % folder_path)
    size = 0
    for path, dirs, files in os.walk(folder_path):
        for f in files:
            fp = os.path.join(path, f)
            stat = os.stat(fp)
            size += stat.st_size
    return size
