// Aquaponics basket hanging on aquarium glass
// Simple test: slotted box + hooks over the glass edge

$fn = 48;

// --- Box ---
box_w   = 120;  // width along the glass (X)
box_d   = 80;   // depth into the tank (Y)
box_h   = 80;   // height (Z)
wall    = 2.4;  // wall thickness
floor_t = 2.4;  // floor thickness

// --- Water slots ---
slot_w      = 3;    // slot width
slot_pitch  = 8;    // slot spacing
slot_margin = 8;    // solid border around slot fields
side_slot_h = 40;   // height of side slots (from floor)

// --- Hook ---
glass_t    = 6;    // aquarium glass thickness
clearance  = 2;    // extra gap for easy fitting
hook_gap   = glass_t + clearance;
hook_w     = 20;   // width of one hook (X)
hook_t     = 3;    // hook material thickness
hook_leg   = 30;   // outer leg length below the bridge
hook_inset = 15;   // hook distance from box side edges

echo(hook_gap = hook_gap);

module slot_field_x(len, field_w, depth) {
    // slots running along Y, distributed along X
    n = floor((field_w - slot_w) / slot_pitch) + 1;
    off = (field_w - ((n - 1) * slot_pitch + slot_w)) / 2;
    for (i = [0 : n - 1])
        translate([off + i * slot_pitch, 0, 0]) cube([slot_w, len, depth]);
}

module box() {
    difference() {
        cube([box_w, box_d, box_h]);
        // hollow
        translate([wall, wall, floor_t]) cube([box_w - 2*wall, box_d - 2*wall, box_h]);
        // floor slots
        translate([slot_margin, slot_margin, -1])
            slot_field_x(box_d - 2*slot_margin, box_w - 2*slot_margin, floor_t + 2);
        // front/back wall slots (vertical)
        translate([slot_margin, -1, floor_t + 4])
            slot_field_x(box_d + 2, box_w - 2*slot_margin, side_slot_h);
        // left/right wall slots
        translate([-1, box_d - slot_margin, floor_t + 4])
            rotate([0, 0, -90])
                slot_field_x(box_w + 2, box_d - 2*slot_margin, side_slot_h);
    }
}

module hook() {
    // bridge over the glass, starting on top of the back wall
    translate([0, box_d - wall, box_h - 0.01])
        cube([hook_w, wall + hook_gap + hook_t, hook_t]);
    // outer leg going down outside the tank
    translate([0, box_d + hook_gap, box_h - hook_leg])
        cube([hook_w, hook_t, hook_leg + hook_t]);
}

box();
for (x = [hook_inset, box_w - hook_inset - hook_w])
    translate([x, 0, 0]) hook();
