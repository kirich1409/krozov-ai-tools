#!/bin/bash
# Best-effort file path extraction from Bash commands
# Recognized: cat, less, head, tail, source, ., grep, input redirection
# Expands: ~, $HOME, $PWD
# Skips: dynamic variables, piped output, subshells

sg_extract_files_from_bash() {
  local command="$1"
  local files=""

  # Split on && and ; to handle chained commands
  local segments
  segments=$(echo "$command" | sed 's/&&/\n/g; s/;/\n/g')

  while IFS= read -r segment; do
    [[ -z "${segment// /}" ]] && continue
    local extracted
    extracted=$(sg_extract_from_segment "$segment")
    if [[ -n "$extracted" ]]; then
      files="${files:+$files$'\n'}$extracted"
    fi
  done <<< "$segments"

  echo "$files"
}

sg_extract_from_segment() {
  local segment="$1"
  segment="$(echo "$segment" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

  local files=""

  # Input redirection: < file
  local redir_file
  if redir_file=$(echo "$segment" | perl -nle 'print $1 if /<\s*(\S+)/' 2>/dev/null) && [[ -n "$redir_file" ]]; then
    local resolved
    resolved=$(sg_resolve_extracted_path "$redir_file")
    [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
  fi

  # Get first word (command name)
  local cmd_word
  cmd_word=$(echo "$segment" | awk '{print $1}')

  case "$cmd_word" in
    cat|less|more)
      local args
      args=$(echo "$segment" | awk '{for(i=2;i<=NF;i++) if(substr($i,1,1)!="-") print $i}')
      while IFS= read -r arg; do
        [[ -z "$arg" ]] && continue
        local resolved
        resolved=$(sg_resolve_extracted_path "$arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      done <<< "$args"
      ;;
    head|tail)
      local last_arg
      last_arg=$(echo "$segment" | awk '{
        skip_next=0
        last=""
        for(i=2;i<=NF;i++) {
          if(skip_next) { skip_next=0; continue }
          if($i ~ /^-/) { if($i ~ /^-[ncq]$/) skip_next=1; continue }
          last=$i
        }
        print last
      }')
      if [[ -n "$last_arg" ]]; then
        local resolved
        resolved=$(sg_resolve_extracted_path "$last_arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      fi
      ;;
    source|.)
      local file_arg
      file_arg=$(echo "$segment" | awk '{print $2}')
      if [[ -n "$file_arg" ]]; then
        local resolved
        resolved=$(sg_resolve_extracted_path "$file_arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      fi
      ;;
    grep|rg)
      local last_arg
      last_arg=$(echo "$segment" | awk '{print $NF}')
      if [[ "$last_arg" != "$cmd_word" && "${last_arg:0:1}" != "-" ]]; then
        if [[ "$last_arg" == */* || "$last_arg" == *.* ]]; then
          local resolved
          resolved=$(sg_resolve_extracted_path "$last_arg")
          [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
        fi
      fi
      ;;
  esac

  echo "$files"
}

sg_resolve_extracted_path() {
  local path="$1"

  # Remove surrounding quotes
  path="${path%\"}"
  path="${path#\"}"
  path="${path%\'}"
  path="${path#\'}"

  # Skip if contains unresolvable variables
  if echo "$path" | perl -ne 'exit(/\$(?!HOME|PWD)[A-Za-z_]/ ? 0 : 1)' 2>/dev/null; then
    return
  fi

  # Expand ~ and known variables
  path=$(sg_resolve_path "$path")

  echo "$path"
}
