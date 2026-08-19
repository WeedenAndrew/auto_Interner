@echo off
REM Remove example assets the README no longer references. Read before running.
setlocal
cd /d "%~dp0"

echo(
echo These files are no longer referenced by README.md or any source file:
echo(
for %%F in (
  "docs\examples\tailored-resume.png"
  "docs\examples\tailored-resume-preview.docx"
  "docs\examples\two-postings.png"
) do (
  if exist %%F echo    %%F
)
echo(
echo Kept on purpose - they are the provenance for the worked example:
echo    docs\examples\posting-sentry.txt
echo    docs\examples\posting-tiktok.txt
echo    docs\examples\two-postings.txt
echo    docs\examples\curated-resume.md
echo(
set /p GO="Delete the unreferenced files? (y/N) "
if /I not "%GO%"=="y" goto :end

for %%F in (
  "docs\examples\tailored-resume.png"
  "docs\examples\tailored-resume-preview.docx"
  "docs\examples\two-postings.png"
) do (
  if exist %%F (
    del %%F
    echo    deleted %%F
  )
)

:end
echo(
echo Done. Nothing was committed.
endlocal
pause
