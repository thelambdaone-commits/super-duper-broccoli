import logging

logger = logging.getLogger("LocalizationSync")


def apply_backward_compatible_aliases() -> None:
    """
    Exposes French technical method signatures as aliases to the new English implementations
    to guarantee zero regressions in test suites, shell scripts, and third-party scripts.
    """
    # 1. Alias LobstarQuantumRunner.enregistrer_job -> register_job
    try:
        from core.quantum_runner import LobstarQuantumRunner
        LobstarQuantumRunner.enregistrer_job = LobstarQuantumRunner.register_job
        logger.info("🔗 [LOCALIZATION SYNC] Aliased LobstarQuantumRunner.enregistrer_job -> register_job")
    except Exception as e:
        logger.warning(f"Could not alias LobstarQuantumRunner: {e}")

    # 2. Alias LobstarCognitiveBrain.synthetiser_decision_cognitive -> synthesize_cognitive_decision
    try:
        from services.lobstar_cognitive_brain import LobstarCognitiveBrain
        LobstarCognitiveBrain.synthetiser_decision_cognitive = LobstarCognitiveBrain.synthesize_cognitive_decision
        logger.info("🔗 [LOCALIZATION SYNC] Aliased LobstarCognitiveBrain.synthetiser_decision_cognitive -> synthesize_cognitive_decision")
    except Exception as e:
        logger.warning(f"Could not alias LobstarCognitiveBrain: {e}")

    # 3. Alias PolymarketPredictiveEngine.predire_pari_gagnant -> predict_winning_bet
    try:
        from schemas.prediction import PolymarketPredictiveEngine
        PolymarketPredictiveEngine.predire_pari_gagnant = PolymarketPredictiveEngine.predict_winning_bet
        logger.info("🔗 [LOCALIZATION SYNC] Aliased PolymarketPredictiveEngine.predire_pari_gagnant -> predict_winning_bet")
    except Exception as e:
        logger.warning(f"Could not alias PolymarketPredictiveEngine: {e}")
