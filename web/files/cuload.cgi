<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="default.css" rel="stylesheet">
<script src="rollover.js"></script>
<title>Backup Configuration</title>
</head>
<body class="ui">
<h1>Backup Configuration</h1>
<p class="lead">The switch is sending its configuration to the TFTP server.</p>
<section>
  <p class="status-line"><span class="spinner" aria-hidden="true"></span><span id="waitText"></span></p>
  <button type="button" class="btn primary" id="continueBtn" onclick="go_on()" disabled>Continue</button>
</section>
<form name="sform"></form>

<script>
PaintButtons("");   // no shell buttons on this page
// Poll getcfgstatus.html every 8 s; it calls update(process_status) when the switch has finished.
var secs = 8, complete = 0, skip = 0;
function setContinue(on) {
  var b = document.getElementById("continueBtn");
  b.disabled = !on;
  document.getElementById("waitText").textContent = on ? "Done. Press Continue." : "Please wait until the transfer has finished\u2026";
}
function tick() {
  secs--;
  if (secs == 0) {
    iw1.location = "getcfgstatus.html";
    if (complete == 0 && false) { secs = 8; window.setTimeout(tick, 1000); }
  } else if (complete == 0) {
    window.setTimeout(tick, 1000);
  }
}
function update(process_status) {
  if (process_status < 0) {
    alert("Error in configuration backup!");
    document.location.href = "fileUpload.html";
  }
  if (skip == 1) { skip = 0; return; }
  complete = 1;
  setContinue(true);
}
function MM_goToURL() {
  var i, args = MM_goToURL.arguments; document.MM_returnValue = false;
  for (i = 0; i < (args.length - 1); i += 2) eval(args[i] + ".location='" + args[i + 1] + "'");
}
setContinue(false);
window.setTimeout(tick, 1000);

function go_on() { document.location.href = "fileUpload.html"; }
</script>
<iframe src="getcfgdwnstatus.html" name="iw1" width="0" height="0" hidden></iframe>
</body>
</html>
