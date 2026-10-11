<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="default.css" rel="stylesheet">
<script src="rollover.js"></script>
<title>Firmware Upload</title>
</head>
<body class="ui">
<h1>Firmware Upload</h1>
<p class="lead">The switch is sending its firmware to the TFTP server.</p>
<section>
<div class="progress" id="progress">
  <div class="bar"><div id="bar"></div></div>
  <p id="progressText">Starting transfer&hellip;</p>
</div>
</section>
<form name="upg" method="post" action="dispdwnstat.cgi" enctype="multipart/form-data"></form>

<script>
PaintButtons("");   // no shell buttons on this page
// Progress: the hidden frame iw1 loads getstatus.html, which calls parent.window.update(current, total, tftp_status).
var t_interval = 1000, phase = 0;
function setBar(pt, text) {
  document.getElementById("bar").style.width = pt + "%";
  document.getElementById("progressText").textContent = text;
}
function start_upgrade() {
  phase = 1;
  setTimeout(check, 250);
}
function update(current, total, tftp_status) {
  if (tftp_status == 1) document.upg.submit();          // transfer finished: continue to dispdwnstat.cgi
  if (current < 0 || phase == 3) {
    phase = 3;
    document.getElementById("progress").className = "progress failed";
    alert("Error in uploading firmware!");
    document.location.href = "fileUpload.html";
    return;
  }
  setTimeout(check, t_interval);
  if (total == 0) return;
  var pt = Math.floor(current * 100 / total);
  if (pt <= 0) return;
  if (pt >= 100) pt = 99;
  phase = 2;
  setBar(pt, current + " bytes written (" + pt + "%)");
}
function check() { iw1.location = "getstatus.html"; }

window.addEventListener("load", start_upgrade);
</script>
<iframe src="getstatus.html" name="iw1" width="0" height="0" hidden></iframe>
</body>
</html>
