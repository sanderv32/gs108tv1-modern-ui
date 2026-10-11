<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="default.css" rel="stylesheet">
<script src="rollover.js"></script>
<title>Firmware Upgrade Complete</title>
</head>
<body class="ui">
<h1>Firmware Upgrade Complete</h1>
<p class="lead">The new image has been written. It becomes active after the switch restarts.</p>
<form id="frestart" name="frm" onsubmit="apply();return false">
<section>
  <h2>Next step <a class="help" href="javascript:void(0)" onclick="newWindow('help1.html#fileDownload','','448','336')" title="Help">?</a></h2>
  <dl class="fields">
    <dt>What now?</dt>
    <dd class="choices">
      <label><input type="radio" name="next_step" id="continue" value="0" onclick="enableImage2()"> Continue running the current firmware</label>
      <label><input type="radio" name="next_step" id="restart" value="1" onclick="enableImage2()"> Restart now</label>
    </dd>
  </dl>
</section>
</form>

<script>
PaintButtons("");   // no shell buttons on this page
function apply() {
  if (document.getElementById("continue").checked) {
    document.location = "fileDownload.html";
  } else if (document.getElementById("restart").checked) {
    document.location = "dlrestart.cgi?confirm=yes";
  } else {
    alert("Choose what to do next.");
  }
}
PaintButtons(CreateEditblBtns('Apply', 'parent.maincontent.apply()', 'btn_Apply'));
</script>
</body>
</html>
