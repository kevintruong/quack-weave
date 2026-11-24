use rusty_quack_core::qw_query::BackendError;

pub(crate) fn reserve_slots(
    budget: &mut usize,
    count: usize,
    bytes_per_slot: usize,
) -> Result<(), BackendError> {
    let bytes = count
        .checked_mul(bytes_per_slot)
        .ok_or(BackendError::BatchBudget)?;
    *budget = budget.checked_sub(bytes).ok_or(BackendError::BatchBudget)?;
    Ok(())
}
