import Toybox.Lang;
using Toybox.Test;
using Toybox.Math;

// Run: monkeyc -t ... and then monkeydo <prg> epix2 -t

(:test)
function stillWatchGivesZero(logger as Test.Logger) as Boolean {
    // Watch still, gravity along z: no shaking, no steering.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [1000, 1000, 1000, 1000];
    var w0 = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, w0, w0, w0);
    logger.debug("still " + r);
    return r[0] < 0.01 && r[1] < 0.01 && r[2] < 0.01;
}

(:test)
function shakingRmsAndPeak(logger as Test.Logger) as Boolean {
    // |a| alternates 900/1100 mG: RMS 100 and largest deviation 100.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [900, 1100, 900, 1100];
    var r = motionMetrics(ax, ay, az, null, null, null);
    logger.debug("shake " + r);
    return (r[0] - 100.0).abs() < 0.5 && (r[1] - 100.0).abs() < 0.5 && r[2] == null;
}

(:test)
function steeringAroundVerticalAxisIndependentOfTilt(logger as Test.Logger) as Boolean {
    // Watch tilted 90 degrees (gravity along x). Rotation around x alternates ±20 degrees/s
    // and should give steer 20. Rotation around y (perpendicular to the vertical) should be ignored.
    var ax = [1000, 1000, 1000, 1000], ay = [0, 0, 0, 0], az = [0, 0, 0, 0];
    var wx = [20.0, -20.0, 20.0, -20.0], wy = [50.0, -50.0, 50.0, -50.0], wz = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, wx, wy, wz);
    logger.debug("steer " + r);
    return (r[2] - 20.0).abs() < 0.5;
}

(:test)
function smoothCurveGivesNoSteeringCorrection(logger as Test.Logger) as Boolean {
    // Constant 30 degrees/s around the vertical axis = a smooth curve, not corrections.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [1000, 1000, 1000, 1000];
    var wz = [30.0, 30.0, 30.0, 30.0], w0 = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, w0, w0, wz);
    logger.debug("curve " + r);
    return r[2] < 0.01;
}
