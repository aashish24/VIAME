#!/usr/bin/env python

import sys
import os
import argparse
import contextlib
import itertools
import signal
import subprocess
import tempfile
import threading

try:
  # Python 3
  import queue
except ImportError:
  # Python 2
  import Queue as queue

sys.dont_write_bytecode = True

import generate_detection_plots
import database_tool

# Character short-cuts
if os.name == 'nt':
  div = '\\'
else:
  div = '/'

lb1 = '\n'
lb2 = lb1 * 2
lb3 = lb1 * 3

# Global flag to see if any video has successfully completed processing
any_video_complete = False

# Helper class to list files with a given extension in a directory
def list_files_in_dir( folder ):
  if not os.path.isdir( folder ):
    exit_with_error( "Input folder \"" + folder + "\" does not exist" )
  return [
    os.path.join(folder, f) for f in sorted(os.listdir(folder))
    if not f.startswith('.')
  ]

def list_files_in_dir_w_ext( folder, extension ):
  return [f for f in list_files_in_dir(folder) if f.endswith(extension)]

# Create a directory if it doesn't exist
def create_dir( dirname, logging=True ):
  if not os.path.exists( dirname ):
    if logging:
      print( "Creating " + dirname )
    os.makedirs( dirname )

CUDA_VISIBLE_DEVICES = "CUDA_VISIBLE_DEVICES"

def get_real_gpu_index(n):
  """Return the real index for the nth GPU as a string.  This respects
  CUDA_VISIBLE_DEVICES

  """
  cvd = os.environ.get(CUDA_VISIBLE_DEVICES)
  if not cvd:  # Treat empty string and None the same
    return str(n)
  # This is an attempt to respect the fact that an invalid index hides
  # the GPUs listed after it
  cvd_parsed = list(itertools.takewhile(lambda i: not i.startswith('-'),
                                        cvd.split(',')))
  if 0 <= n < len(cvd_parsed):
    return cvd_parsed[n]
  else:
    raise IndexError('Only {} visible GPUs; you asked for number {}!'
                     .format(len(cvd_parsed), n))

def execute_command( cmd, stdout=None, stderr=None, gpu=None ):
  if gpu is None:
    env = None
  else:
    env = dict(os.environ)
    env[CUDA_VISIBLE_DEVICES] = get_real_gpu_index(gpu)
  return subprocess.call(cmd, stdout=stdout, stderr=stderr, env=env)

def get_script_path():
  return os.path.dirname( os.path.realpath( sys.argv[0] ) )

def get_pipeline_cmd( debug=False ):
  if os.name == 'nt':
    if debug:
      return ['pipeline_runner.exe']
    else:
      return ['pipeline_runner.exe']
  else:
    if debug:
      return ['gdb', '--args', 'pipeline_runner']
    else:
      return ['pipeline_runner']

def log_info( msg ):
  sys.stdout.write( msg )
  sys.stdout.flush()

def exit_with_error( error_str, force=False ):
  log_info( lb1 + 'ERROR: ' + error_str + lb2 )
  # Kill this process to end all threads
  if not isinstance(threading.current_thread(), threading._MainThread):
    if os.name == 'nt':
      os.kill(os.getpid(), signal.SIGTERM)
    else:
      os.kill(os.getpid(), signal.SIGKILL)
  # Default exit case, if main thread
  sys.exit(0)

def check_file( filename ):
  if not os.path.exists( filename ):
    exit_with_error( "Unable to find: " + filename )
  return filename

@contextlib.contextmanager
def get_log_output_files( output_prefix ):
  if os.name == 'nt':
    with open(output_prefix + '.out.txt', 'w') as fo, \
         open(output_prefix + '.err.txt', 'w') as fe:
      yield dict(stdout=fo, stderr=fe)
  else:
    with open(output_prefix + '.txt', 'w') as fo:
      yield dict(stdout=fo, stderr=fo)

def find_file( filename ):
  if( os.path.exists( filename ) ):
    return filename
  elif os.path.exists( get_script_path() + div + filename ):
    return get_script_path() + div + filename
  else:
    exit_with_error( "Unable to find " + filename )

def make_filelist_for_image_dir( input_dir, output_dir, output_name ):
  # The most common extension in the folder is most likely images.
  # Sometimes people have small text files alongside the images
  # so just choose the most common filetype.
  exts = dict()
  files = dict()
  for f in os.listdir( input_dir ):
    f_fp = os.path.join( input_dir, f )
    if os.path.isfile( f_fp ):
      _, ext = os.path.splitext( f )
      if ext in exts:
        exts[ext] += 1
        files[ext].append( f_fp )
      else:
        exts[ext] = 1
        files[ext] = [ f_fp ]
  if len(exts) == 0:
    return ""

  top_ext = sorted( exts, key=exts.get, reverse=True )[0]

  # Write out list to file
  output_file = os.path.join( output_dir, output_name + ".txt" )
  fout = open( output_file, "w" )
  for f in files[top_ext]:
    fout.write( f + lb1 )
  fout.close()
  return output_file

# Other helpers
def signal_handler( signal, frame ):
  exit_with_error( 'Processing aborted, see you next time' )

def fset( setting_str ):
  return ['-s', setting_str]

def video_output_settings_list( options, basename ):
  output_dir = options.output_directory

  return list(itertools.chain(
    fset( 'detector_writer:file_name=' + output_dir + div + basename + '_detections.csv' ),
    fset( 'track_writer:file_name=' + output_dir + div + basename + '_tracks.csv' ),
    fset( 'track_writer:stream_identifier=' + basename ),
    fset( 'track_writer_db:writer:db:video_name=' + basename ),
    fset( 'track_writer_kw18:file_name=' + output_dir + div + basename + '.kw18' ),
    fset( 'descriptor_writer_db:writer:db:video_name=' + basename ),
    fset( 'track_descriptor:uid_basename=' + basename ),
    fset( 'kwa_writer:output_directory=' + output_dir ),
    fset( 'kwa_writer:base_filename=' + basename ),
    fset( 'kwa_writer:stream_id=' + basename ),
  ))

def plot_settings_list( options, basename ):
  output_dir = options.output_directory

  return list(itertools.chain(
    fset( 'detector_writer:file_name=' + output_dir + div + basename + '_detections.csv' ),
    fset( 'kwa_writer:output_directory=' + output_dir ),
    fset( 'kwa_writer:base_filename=' + basename ),
    fset( 'kwa_writer:stream_id=' + basename ),
  ))

def archive_dimension_settings_list( options ):
  if len( options.archive_width ) > 0:
    return list(itertools.chain(
      fset( 'kwa_writer:fixed_col_count=' + options.archive_width ),
      fset( 'kwa_writer:fixed_row_count=' + options.archive_height ),
    ))
  return []

def object_detector_settings_list( options ):
  if len( options.detection_threshold ) > 0:
    return list(itertools.chain(
      fset( 'detector:detector:darknet:thresh=' + options.detection_threshold ),
      fset( 'detector_filter:filter:class_probablity_filter:threshold=' + options.detection_threshold ),
      fset( 'track_initializer:track_initializer:threshold:'
            'filter:class_probablity_filter:threshold=' + options.detection_threshold ),
    ))
  return []

def video_frame_rate_settings_list( options ):
  output = []
  if len( options.frame_rate ) > 0:
    output += fset( 'downsampler:target_frame_rate=' + options.frame_rate )
  if len( options.batch_size ) > 0:
    output += fset( 'downsampler:burst_frame_count=' + options.batch_size )
  if len( options.batch_skip ) > 0:
    output += fset( 'downsampler:burst_frame_break=' + options.batch_skip )
  if len( options.input_frame_rate ) > 0:
    output += fset( 'input:frame_time' + options.input_frame_rate )
  return output

def remove_quotes( input_str ):
  return input_str.replace( "\"", "" )

# Process a single video
def process_video_kwiver( input_name, options, is_image_list=False, base_ovrd='', gpu=None ):

  if gpu is None:
    gpu = 0

  log_info( 'Processing: {} on CPU... '.format(os.path.basename(input_name)) )

  # Get video name without extension and full path
  if len( base_ovrd ) > 0:
    basename = base_ovrd
  else:
    basename = os.path.splitext( os.path.basename( input_name ) )[0]

  # Formulate input setting string
  if not os.path.exists( input_name ):
    log_info( 'Skipped ({})'.format(gpu) + lb1 )
    return
  elif os.path.isdir( input_name ):
    input_name = make_filelist_for_image_dir( input_name, options.output_directory, basename )
    if len( input_name ) == 0:
      log_info( 'Skipped ({})'.format(gpu) + lb1 )
      return
    is_image_list = True

  input_setting = fset( 'input:video_filename=' + input_name )

  if is_image_list:
    name_no_path = os.path.basename( input_name )
    input_setting += fset( 'track_writer:writer:viame_csv:stream_identifier=' + name_no_path )
  else:
    input_setting += fset( 'input:video_reader:type=vidl_ffmpeg' )
    input_setting += fset( 'track_writer:writer:viame_csv:write_time_as_uid=true' )

  # Formulate command
  command = (get_pipeline_cmd( options.debug ) +
             ['-p', find_file( options.pipeline )] +
             input_setting)

  if not is_image_list:
    command += video_frame_rate_settings_list( options )

  command += video_output_settings_list( options, basename )
  command += archive_dimension_settings_list( options )
  command += object_detector_settings_list( options )

  if len( options.input_detections ) > 0:
    command += fset( "detection_reader:file_name=" + options.input_detections )

  try:
    if len( options.extra_settings ) > 0:
      for extra_option in options.extra_settings:
        command += fset( " ".join( extra_option ) )
  except:
    pass

  # Process command, possibly with logging
  log_base = ""
  if len( options.log_directory ) > 0 and not options.debug:
    log_base = options.output_directory + div + options.log_directory + div + basename
    with get_log_output_files( log_base ) as kwargs:
      res = execute_command( command, gpu=gpu, **kwargs )
  else:
    res = execute_command( command, gpu=gpu )

  global any_video_complete

  if res == 0:
    log_info( 'Success ({})'.format(gpu) + lb1 )
    any_video_complete = True
  else:
    log_info( 'Failure ({})'.format(gpu) + lb1 )

    if res == -11:
      exit_with_error( 'Out of disk space' )

    if not any_video_complete:
      if len( log_base ) > 0:
        exit_with_error( 'Processing failed, check ' + log_base + '.txt, terminating.' )
      else:
        exit_with_error( 'Processing failed, terminating.' )
    elif len( log_base ) > 0:
      log_info( lb1 + 'Check ' + log_base + '.txt for error messages' + lb1 )

def split_image_list(image_list_file, n, dir):
  """Create and return the paths to n temp files that when interlaced
  reproduce the original file.  The names are created
  deterministically like "orig_name_part0.ext", "orig_name_part1.ext",
  etc., but with the original name used as is when n == 1.

  Existing files with the same names are overwritten without question.
  Deleting the files is the responsibility of the caller.

  """
  bn = os.path.basename(image_list_file)
  if n == 1:
    file_names = [bn]
  else:
    prefix, suffix = os.path.splitext(bn)
    num_width = len(str(n - 1))
    file_names = [
      prefix + '_part{:0{}}'.format(i, num_width) + suffix
      for i in range(n)
    ]
  file_names = [os.path.join(dir, fn) for fn in file_names]

  try:
    # Build manually to have the intermediate state in case of error
    tempfiles = []
    for fn in file_names:
      tempfiles.append(open(fn, 'w'))
    with open(image_list_file) as f:
      for i, line in enumerate(f):
        tempfiles[i % n].write(line)
  finally:
    for f in tempfiles:
      f.close()
  return file_names

# Main Function
if __name__ == "__main__" :

  parser = argparse.ArgumentParser(description="Process new videos",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument("-v", dest="input_video", default="",
                      help="Input single video to process")

  parser.add_argument("-d", dest="input_dir", default="",
                      help="Input directory of videos or image folders to process")

  parser.add_argument("-l", dest="input_list", default="",
                      help="Input list of image files to process")

  parser.add_argument("-p", dest="pipeline", default="pipelines" + div + "index_default.res.pipe",
                      help="Input pipeline for processing video or image data")

  parser.add_argument("-s", dest="extra_settings", action='append', nargs='*',
                      help="Extra command line arguments for the pipeline runner")

  parser.add_argument("-id", dest="input_detections", default="",
                      help="Input detections around which to create descriptors")

  parser.add_argument("-o", dest="output_directory", default="database",
                      help="Output directory to store files in")

  parser.add_argument("-logs", dest="log_directory", default="Logs",
                      help="Output sub-directory for log files, if empty will not use files")

  parser.add_argument("-frate", dest="frame_rate", default="",
                      help="Processing frame rate over-ride to process videos at, specified "
                      "in hertz (frames per second)" )

  parser.add_argument("-fbatch", dest="batch_size", default="",
                      help="Optional number of frames to process in batches")

  parser.add_argument("-fskip", dest="batch_skip", default="",
                      help="If batching frames, number of frames to skip between batches")

  parser.add_argument("-ifrate", dest="input_frame_rate", default="",
                      help="Input frame rate over-ride to process videos at. This is useful "
                      "for specifying the frame rate of input image lists, which typically "
                      "don't have frame rates")

  parser.add_argument("-objects", dest="objects", default="fish",
                      help="Objects to generate plots for")

  parser.add_argument("-plot-threshold", dest="plot_threshold", default="0.25",
                      help="Threshold to generate plots for")

  parser.add_argument("-detection-threshold", dest="detection_threshold", default="",
                      help="Optional detection threshold over-ride parameter")

  parser.add_argument("-smooth", dest="smooth", default="1",
                      help="Smoothing factor for plots")

  parser.add_argument("-archive-height", dest="archive_height", default="",
                      help="Advanced: Optional video archive height over-ride")

  parser.add_argument("-archive-width", dest="archive_width", default="",
                      help="Advanced: Optional video archive width over-ride")

  parser.add_argument("--init-db", dest="init_db", action="store_true",
                      help="Re-initialize database")

  parser.add_argument("--build-index", dest="build_index", action="store_true",
                      help="Build searchable index on completion")

  parser.add_argument("--ball-tree", dest="ball_tree", action="store_true",
                      help="Use a ball tree for the searchable index")

  parser.add_argument("--debug", dest="debug", action="store_true",
                      help="Run with debugger attached to process")

  parser.add_argument("--detection-plots", dest="detection_plots", action="store_true",
                      help="Produce per-video detection plot summaries")

  parser.add_argument("-install", dest="install_dir", default="",
                      help="Optional install dir over-ride for all application "
                      "binaries. If this is not specified, it is expected that all "
                      "viame binaries are already in our path.")

  parser.add_argument("-g", "--gpu-count", default=1, type=int, metavar='N',
                      help="Parallelize the ingest by using the first N GPUs in parallel")

  args = parser.parse_args()

  # Error checking
  process_data = True

  number_input_args = sum(len(inp_x) > 0 for inp_x in [args.input_video, args.input_dir, args.input_list])
  if number_input_args == 0:
    if not args.build_index and not args.detection_plots:
      exit_with_error( "Either input video or input directory must be specified" )
    else:
      process_data = False

  elif number_input_args > 1:
    exit_with_error( "Only one of input video, directory, or list should be specified, not more" )

  signal.signal( signal.SIGINT, signal_handler )

  # Initialize database
  if args.init_db:
    if len( args.log_directory ) > 0:
      init_log_file = args.output_directory + div + args.log_directory + div + "database_log.txt"
    else:
      init_log_file = ""
    if not database_tool.init( log_file=init_log_file ):
      if len( args.log_directory ) > 0:
        exit_with_error( "Unable to initialize database, check " + init_log_file + lb2 +
                         "You may have another database running on your system, or ran "
                         "a failed operation in the past and need to re-log or restart." )
      else:
        exit_with_error( "Unable to initialize database" )

  # Call processing pipelines on all input data
  if process_data:

    # Identify all videos to process
    if len( args.input_list ) > 0:
      video_list = split_image_list( args.input_list, args.gpu_count, args.output_directory )
      is_image_list = True
    elif len( args.input_dir ) > 0:
      video_list = list_files_in_dir( args.input_dir )
      is_image_list = False
    else:
      video_list = [args.input_video]
      is_image_list = False

    if len( video_list ) == 0:
      exit_with_error( "No videos found for ingest in given folder, exiting." )
    elif not is_image_list:
      video_str = " video" if len( video_list ) == 1 else " videos"
      log_info( "Processing " + str( len( video_list ) ) + video_str + lb2 )

    # Get required paths
    pipeline_loc = args.pipeline

    if len( args.output_directory ) > 0:
      create_dir( args.output_directory )

    if len( args.log_directory ) > 0:
      create_dir( args.output_directory + div + args.log_directory )

    # Process videos in parallel, one per GPU
    video_queue = queue.Queue()
    for video_name in video_list:
      if os.path.isfile( video_name ) or os.path.isdir( video_name ):
        video_queue.put( video_name )

    def process_video_thread( gpu ):
      while True:
        try:
          video_name = video_queue.get_nowait()
        except queue.Empty:
          break
        process_video_kwiver( video_name, args, is_image_list, gpu=gpu )

    threads = [threading.Thread(target=process_video_thread, args=(gpu,))
               for gpu in range(args.gpu_count)]

    for thread in threads:
      thread.start()
    for thread in threads:
      thread.join()

    if is_image_list:
      for image_list in video_list:  # Clean up after split_image_list
        os.unlink(image_list)

    if not video_queue.empty():
      exit_with_error( "Some videos were not processed!" )

  # Build out detection vs time plots
  if args.detection_plots:
    log_info( "Generating data plots" + lb1 )
    generate_detection_plots.aggregate_plot( args.output_directory,
                                    args.objects.split(","),
                                    float( args.plot_threshold ),
                                    float( args.frame_rate ),
                                    int( args.smooth ) )

  # Build searchable index
  if args.build_index:
    log_info( lb1 + "Building searchable index" + lb2 )

    if len( args.log_directory ) > 0:
      index_log_file = args.output_directory + div + args.log_directory + div + "smqtk_indexer.txt"
    else:
      index_log_file = ""

    if args.ball_tree:
      if not database_tool.build_balltree_index( remove_quotes( args.install_dir ),
                                                log_file=index_log_file ):
        exit_with_error( "Unable to build index" )
    else:
      if not database_tool.build_standard_index( remove_quotes( args.install_dir ),
                                                 log_file=index_log_file ):
        exit_with_error( "Unable to build index" )

  # Output complete message
  if os.name == 'nt':
    log_info( lb1 + "Processing complete, close this window before launching any GUI." + lb2 )
  else:
    log_info( lb1 + "Processing complete" + lb2 )
