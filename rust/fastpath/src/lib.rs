//! pf_fastpath: two hot paths for playfellow-coop, written fresh during the hackathon.
//! Plain C functions (no Python headers, no dependencies); the Python side loads the DLL with ctypes and has an
//! identical pure-Python fallback, so a PC without this DLL behaves the same, only slower.
//!
//! The rules the Python twin follows too, so results match exactly:
//!   * grid A*: 4 neighbours in the order up, right, down, left; unit cost; Manhattan heuristic;
//!     the open list orders by (f, h, index), smallest first; a cell's parent changes only when its cost strictly drops.

use std::cmp::Reverse;
use std::collections::BinaryHeap;

pub const OK_NO_PATH: i32 = -1;
pub const BAD_ARGS: i32 = -2;
pub const OUT_TOO_SMALL: i32 = -3;
const MAX_SIDE: u32 = 16_384;

/// Shortest 4-connected path on a grid. `cells` holds `w*h` bytes, row by row: 0 = free, anything else = blocked.
/// `start` and `goal` are cell indexes (y*w + x). The path (start..=goal) is written to `out`.
/// Returns the number of cells written, -1 when there is no path, -2 for bad arguments, -3 when `out` is too small.
///
/// # Safety
/// `cells` must point to `w*h` readable bytes and `out` to `out_cap` writable u32 values.
#[no_mangle]
pub unsafe extern "C" fn pf_astar_grid(
    w: u32, h: u32, cells: *const u8, start: u32, goal: u32, out: *mut u32, out_cap: u32,
) -> i32 {
    if cells.is_null() || out.is_null() || w == 0 || h == 0 || w > MAX_SIDE || h > MAX_SIDE {
        return BAD_ARGS;
    }
    let n = (w as usize) * (h as usize);
    if (start as usize) >= n || (goal as usize) >= n {
        return BAD_ARGS;
    }
    let grid = std::slice::from_raw_parts(cells, n);
    if grid[start as usize] != 0 || grid[goal as usize] != 0 {
        return BAD_ARGS;
    }
    let width = w as usize;
    let goal_x = (goal as usize) % width;
    let goal_y = (goal as usize) / width;
    let heuristic = |index: usize| -> u32 {
        let x = index % width;
        let y = index / width;
        (x.abs_diff(goal_x) + y.abs_diff(goal_y)) as u32
    };

    let unseen = u32::MAX;
    let mut cost = vec![unseen; n];
    let mut parent = vec![u32::MAX; n];
    let mut open: BinaryHeap<Reverse<(u32, u32, u32)>> = BinaryHeap::new();
    cost[start as usize] = 0;
    open.push(Reverse((heuristic(start as usize), heuristic(start as usize), start)));

    while let Some(Reverse((_f, _h, index))) = open.pop() {
        let here = index as usize;
        if index == goal {
            break;
        }
        let g_here = cost[here];
        // a stale entry: a cheaper way to this cell was found after it was queued
        if _f != g_here + heuristic(here) {
            continue;
        }
        let x = here % width;
        let y = here / width;
        // up, right, down, left
        let mut next = [usize::MAX; 4];
        if y > 0 { next[0] = here - width; }
        if x + 1 < width { next[1] = here + 1; }
        if y + 1 < h as usize { next[2] = here + width; }
        if x > 0 { next[3] = here - 1; }
        for &there in next.iter() {
            if there == usize::MAX || grid[there] != 0 {
                continue;
            }
            let g = g_here + 1;
            if g < cost[there] {
                cost[there] = g;
                parent[there] = index;
                let hh = heuristic(there);
                open.push(Reverse((g + hh, hh, there as u32)));
            }
        }
    }

    if cost[goal as usize] == unseen {
        return OK_NO_PATH;
    }
    let length = cost[goal as usize] as usize + 1;
    if length > out_cap as usize {
        return OUT_TOO_SMALL;
    }
    let mut at = goal;
    for slot in (0..length).rev() {
        *out.add(slot) = at;
        at = parent[at as usize];
    }
    length as i32
}

/// How many of `n` bytes differ between `a` and `b` by MORE than `threshold` (grey levels). Used to decide whether a
/// 32x32 thumbnail changed enough to count as a new keyframe. Returns u32::MAX for null pointers.
///
/// # Safety
/// `a` and `b` must each point to `n` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn pf_changed_cells(a: *const u8, b: *const u8, n: u32, threshold: u8) -> u32 {
    if a.is_null() || b.is_null() {
        return u32::MAX;
    }
    let left = std::slice::from_raw_parts(a, n as usize);
    let right = std::slice::from_raw_parts(b, n as usize);
    let mut count = 0u32;
    for (x, y) in left.iter().zip(right.iter()) {
        if x.abs_diff(*y) > threshold {
            count += 1;
        }
    }
    count
}

/// The crate's own version marker, so the Python side can check it loaded the DLL it expects.
#[no_mangle]
pub extern "C" fn pf_fastpath_abi() -> u32 {
    1
}
